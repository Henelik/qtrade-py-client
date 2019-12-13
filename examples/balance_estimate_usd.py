from decimal import Decimal
from qtrade_client.api import QtradeAPI

"""
Estimate the balance of the account in USD.
"""

COIN = Decimal('.00000001')

api = None


def balance_estimate_usd(key):
    global api

    # create the API object with access to our account
    api = QtradeAPI("https://api.qtrade.io", key=key)
    # get a dictionary of all coin balances, including currency in orders
    balances = api.balances_merged()
    # the total of our account's value, in BTC
    total_btc = Decimal(0)
    # iterate over the coins in our account
    for coin, balance in balances.items():
        if coin == "BTC":
            # if we have BTC, add it to our total
            total_btc += balance
        else:
            # convert other coins to BTC and add to the total
            total_btc += coin_to_btc(coin, balance)
    # convert our BTC total to USD and return it
    return btc_to_usd(total_btc).quantize(COIN)


# convert an amount of some coin to BTC using the market midpoint
def coin_to_btc(coin, amount):
    global api

    market_string = coin + "_BTC"

    # get the ticker for this market
    res = api.get("/v1/ticker/" + market_string)

    # calculate the midpoint of the market
    bid, ask = Decimal(res['bid']), Decimal(res['ask'])
    midpoint = ((bid + ask) / 2).quantize(COIN)

    return midpoint * amount


# convert BTC to USD
def btc_to_usd(amount):
    global api

    # get the BTC/USD conversion rate from the API
    btc_price = api.get('/v1/currency/BTC')['currency']['config']['price']

    return Decimal(amount) * Decimal(btc_price)


if __name__ == "__main__":
    # replace this with your API key to test this example
    key = "1:1111111111111111111111111111111111111111111111111111111111111111"
    print(balance_estimate_usd(key))
