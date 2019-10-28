import requests
import requests.auth
import time
import json as _json
import urllib.parse
import logging
import base64

from hashlib import sha256
from urllib.parse import urlparse

log = logging.getLogger("qtrade")


class Currency(dict):
    def __value__(self):
        return self.code


class APIException(Exception):
    def __init__(self, message, code, errors):
        super().__init__(message)
        self.code = code
        self.errors = errors


class QtradeAuth(requests.auth.AuthBase):
    def __init__(self, key):
        self.key_id, self.key = key.split(":")

    def __call__(self, req):
        # modify and return the request
        timestamp = str(int(time.time()))
        url_obj = urlparse(req.url)

        request_details = req.method + "\n"
        uri = url_obj.path
        if url_obj.query:
            uri += "?" + url_obj.query
        request_details += uri + "\n"
        request_details += timestamp + "\n"
        if req.body:
            if isinstance(req.body, str):
                request_details += req.body + "\n"
            else:
                request_details += req.body.decode('utf8') + "\n"
        else:
            request_details += "\n"
        request_details += self.key
        hsh = sha256(request_details.encode("utf8")).digest()
        signature = base64.b64encode(hsh)
        req.headers.update({
            "Authorization": "HMAC-SHA256 {}:{}".format(self.key_id, signature.decode("utf8")),
            "HMAC-Timestamp": timestamp
        })
        return req


class QtradeAPI(object):
    def __init__(self, endpoint, origin=None, email='Unk', key=None):
        self.user_id = None
        self.email = email
        self.endpoint = endpoint
        self.markets = {}
        self.origin = origin
        self.token = None
        self.rs = requests.Session()
        if key is not None:
            self.set_hmac(key)

        self.honor_ratelimit = True
        self.rl_remaining = 99
        self.rl_reset_at = time.time()
        self.rl_limit = 120
        # Set to 1 to disable soft threshold, 0 will always sleep between calls
        # if needed (no burst at all)
        self.rl_soft_threshold = 0.5

    def clone(self):
        """ Returns a new QtradeAPI instance with stripped auth but the same
        endpoint configuration. Useful for testing toolchains that might point
        at multiple testing endpoints and 'inherit' from some base endpoint
        config """
        return type(self)(self.endpoint)

    def login(self, email, password):
        """ Login with username and password to get a JWT token. Not
        recommended for production use, but can be okay for quick testing. """
        resp = self._req('post', "/v1/login", json={
            "email": email,
            "password": password,
        })
        self.user_id = resp['user_id']
        self.token = resp['token']

    def set_hmac(self, hmac_pair):
        """ hmac_pair should be in "1:11111..." format, with keyid then key """
        self.rs.auth = QtradeAuth(hmac_pair)

    def balances(self):
        return {b['currency']: b['balance'] for b in self.get("/v1/user/balances")['balances']}

    def get(self, endpoint, *args, **kwargs):
        return self._req('get', endpoint, *args, **kwargs)

    def post(self, endpoint, *args, **kwargs):
        return self._req('post', endpoint, *args, **kwargs)

    def orders(self, open=None, older_than=None, newer_than=None):
        if isinstance(open, bool):
            open = str(open).lower()
        return self.get("/v1/user/orders", open=open, older_than=older_than, newer_than=newer_than)['orders']

    def order(self, market_id=None, market_string=None):
        if market_id is not None and market_string is not None:
            raise ValueError("market_id and market_string are mutually exclusive")
        if market_string is not None:
            market_id = self.markets[market_string]['id']

    def balances_all(self):
        pass

    def balances_merged(self):
        pass

    @property
    def markets(self):
        # Index our market information by market string
        common = self.api.get("/v1/common")
        self.currencies_map = {c['code']: c for c in common['currencies']}
        # Set some convenience keys so we can pass around just the dict
        for m in common['markets']:
            m['string'] = "{market_currency}_{base_currency}".format(**m)
            m['base_currency'] = self.currencies_map[m['base_currency']]
        self.market_map = {m['string']: m for m in common['markets']}

    def _req(self, method, endpoint, silent_codes=[], headers={}, json=None, params=None, is_retry=False, **kwargs):
        # If limit is completely exhausted, sleep until full reset. Clamp to
        # min 0 to not bomb out if reset_at is in past
        if self.honor_ratelimit and self.rl_remaining <= 0:
            must_wait = max(0, self.rl_reset_at - time.time())
            if must_wait >= 5:
                log.info("Ratelimit hit, sleeping for {:,}".format(must_wait))
            time.sleep(must_wait)

        # If limit is >self.rl_soft_threshold % used, sleep the appropriate
        # amount to avoid hitting a big wait
        soft_limit = int(self.rl_limit * (1 - self.rl_soft_threshold))
        if self.honor_ratelimit and self.rl_remaining <= soft_limit:
            sec_to_reset = self.rl_reset_at - time.time()
            must_wait = max(0, sec_to_reset / float(self.rl_remaining))
            time.sleep(must_wait)

        # Inject the auth token header if applicable
        if self.token:
            headers['Authorization'] = "Bearer {}".format(self.token)

        # We remove all kwargs that might be intended for our session.request
        requests_kwarg_keys = ['data', 'cookies', 'files', 'auth', 'timeout', 'allow_redirects', 'proxies', 'hooks', 'stream', 'verify', 'cert']
        requests_kwargs = {}
        for key in requests_kwarg_keys:
            requests_kwargs[key] = kwargs.pop(key, None)

        url = urllib.parse.urljoin(self.endpoint, endpoint)

        # Support legacy usage of the json parameter, but prefer passing POST
        # params as kwargs
        if method.lower() == "post" and json is None:
            json = kwargs
        req_json = _json.dumps(json)

        # Support passing params just because...
        if method.lower() == "get" and params is None:
            params = kwargs

        res = self.rs.request(method, url, headers=headers, json=json, params=params, **requests_kwargs)
        self.rl_reset_at = time.time() + int(res.headers.get('X-Ratelimit-Reset', 0))
        self.rl_limit = int(res.headers.get('X-Ratelimit-Limit', 100))
        self.rl_remaining = int(res.headers.get('X-Ratelimit-Remaining', 99))
        if requests_kwargs.get('stream') is True:
            log.debug("GET streaming {}".format(url))
            for ln in res.iter_lines():
                print(ln.decode('utf8'))
            return

        # We've hit the rate limit, so retry. Code at beginning of call
        # will proc now that we've populated rl_limit, etc
        if res.status_code == 429 and is_retry is False:
            return self._req(method, endpoint, silent_codes=silent_codes, headers=headers, json=json, params=params, is_retry=True, **kwargs)

        try:
            ret = res.json()
        except Exception:
            if res.status_code > 299:
                log.warn("{} {} {} req={} res=\n{}".format(
                    method, url, res.status_code, req_json, res.text))
                raise APIException("Invalid return code from backend", res.status_code, [])
            else:
                return True

        if res.status_code > 299:
            if res.status_code not in silent_codes:
                log.warn("{} {} {} req={} res=\n{}".format(
                    method, url, res.status_code, req_json, res.text))
            errors = [e['code'] for e in ret['errors']]
            raise APIException("Invalid return code from backend", res.status_code, errors)

        log.debug("GET {} req={} res={}".format(url, req_json, ret))
        return ret['data']
