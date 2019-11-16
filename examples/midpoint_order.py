from decimal import Decimal
from qtrade_client.api import QtradeAPI, APIException
import time

COIN = Decimal('.00000001')

# replace this with your API key to test this example
key = "1:1111111111111111111111111111111111111111111111111111111111111111"

# create a QtradeAPI object and pass it the API endpoint and our API key
api = QtradeAPI("https://api.qtrade.io", key=key)

# keep track of the active order's information
active_order = None

# the string identifier of the market we want to trade on.
# market strings are always in (market coin | base coin) format
market = 'DOGE_BTC'

while True:
    # get the ticker for the DOGE/BTC market
    res = api.get("/v1/ticker/" + market)

    # calculate the midpoint of the market
    bid, ask = Decimal(res['bid']), Decimal(res['ask'])
    midpoint = ((bid + ask) / 2).quantize(COIN)

    # if there is no previous order, place a new one
    if active_order is None:
        # place an order to buy as much DOGE as we can for .00011 BTC
        # fees will be taken from our BTC balance when the order is placed
        active_order = api.order('buy_limit', midpoint, value=0.00011,
                                 market_string=market, prevent_taker=True)['order']
    else:
        # cancel the old order if the midpoint has changed since it was placed
        if midpoint != Decimal(active_order['price']):
            # cancel the previous order
            api.post("/v1/user/cancel_order", json={'id': active_order['id']})

        # make sure our order information is up to date
        active_order = api.get("/v1/user/order/" +
                               str(active_order['id']))['order']

        # place a new order if the old one got cancelled or filled
        if active_order['open'] is not True:
            active_order = api.order('buy_limit', midpoint, value=0.00011,
                                     market_string=market, prevent_taker=True)['order']

    time.sleep(5)
