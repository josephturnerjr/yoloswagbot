from twisted.words.protocols import irc
from twisted.internet import reactor, protocol, ssl
from twisted.python import log

import datetime, time, sys, sqlite3
import requests

class LameError(Exception):
    pass

class NoCashError(Exception):
    pass

class NoSharesError(Exception):
    pass

class YoloSwag(object):
    def __init__(self, db_file='swag.db', init_amt=10000.0, trade_cost = 7.0):
        self.init_amt = 10000.0
        self.trade_cost = trade_cost
        self.conn = sqlite3.connect(db_file)
        self.init_tables()

    def init_tables(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS players
                     (id integer primary key, nick text unique, cash real)''')
        c.execute('''CREATE TABLE IF NOT EXISTS buys
                     (player_id integer, symbol text, price real, shares integer, purchase_date timestamp)''')
        self.conn.commit()

    def register(self, nick):
        with self.conn:
            self.conn.execute("insert into players (nick, cash) values (?, ?)", (nick, self.init_amt))

    def buy(self, nick, symbol, shares):
        symbol = symbol.upper()
        if shares < 1:
            raise LameError("Bro, gonna try to sell zero shares? Mad bullish imo")
        price = self.lookup_price(symbol)
        cost = self.trade_cost + (shares * price)
        with self.conn:
            pid, holdings = self.conn.execute("select id, cash from players where nick = ?", (nick,)).fetchone()
            if holdings < cost:
                raise NoCashError("Bro, you don't got the cash, you're only sittin' on %s" % holdings)
            self.conn.execute("update players set cash = ? where id = ?", (holdings - cost, pid))
            self.conn.execute("insert into buys (player_id, symbol, price, shares, purchase_date) values (?,?,?,?,?)", (pid, symbol, price, shares, datetime.datetime.now()))
        return price

    def sell(self, nick, symbol, shares):
        symbol = symbol.upper()
        price = self.lookup_price(symbol)
        with self.conn:
            pid, holdings = self.conn.execute("select id, cash from players where nick = ?", (nick,)).fetchone()
            held = self.conn.execute("select sum(shares) from buys where player_id = ? and symbol = ?", (pid, symbol)).fetchone()[0]
            if shares == "all":
                shares = held
            else:
                shares = int(shares)
            if shares < 1:
                raise LameError("Bro, gonna try to sell zero shares? Mad bullish imo")
            if held < shares:
                raise NoSharesError("Bro, you've only got %s shares of %s" % (held, symbol))
            value = shares * price - self.trade_cost
            self.conn.execute("insert into buys (player_id, symbol, price, shares, purchase_date) values (?,?,?,?,?)", (pid, symbol, price, -shares, datetime.datetime.now()))
            self.conn.execute("update players set cash = ? where id = ?", (holdings + value, pid))
        return (shares, price)

    def holdings(self, nick):
        with self.conn:
            pid, holdings = self.conn.execute("select id, cash from players where nick = ?", (nick,)).fetchone()
            positions = [row for row in self.conn.execute("select symbol, sum(shares) from buys where player_id = ? group by symbol having sum(shares) > 0", (pid,))]
        r = "Your holdings:\n\t### CASH: $%s\n" % (holdings,)
        for symbol, shares in positions:
            r += "\t%s: %s shares\n" % (symbol, shares)
        return r
            
    def lookup_price(self, symbol):
        url = "http://dev.markitondemand.com/MODApis/Api/v2/Quote/json?symbol=%s" % symbol
        resp = requests.get(url).json()
        if resp['Status'] == 'SUCCESS':
            return resp['LastPrice']
        else:
            return resp.get('Message', 'API Error')

    def cash(self):
        with self.conn:
            players = [row for row in self.conn.execute("select nick, cash from players order by cash desc")]
            r = "Leaderboard:\n\t%s: $%s ***SwaggerChampion***\n" % players[0]
            for (nick, cash) in players[1:]:
                r += "\t%s: $%s" % (nick, cash)
            return r

    def close(self):
        self.conn.close()


class YoloSwagBot(irc.IRCClient):
    nickname = "yoloswagbot"
    
    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        self.swag = YoloSwag()

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self, reason)
        self.swag.close()

    def signedOn(self):
        self.join(self.factory.channel)

    def joined(self, channel):
        self.msg(channel, "#YoloSwag420")

    def privmsg(self, user, channel, msg):
        user = user.split('!', 1)[0]
        if channel != self.nickname and msg.startswith(self.nickname + ":"):
            try:
                cmd_args = msg.split()[1:]
                cmd = cmd_args[0]
                args = cmd_args[1:]
                if cmd == "leaderboard":
                    self.msg(channel, str(self.swag.cash()))
                elif cmd == "holdings":
                    self.msg(channel, str(self.swag.holdings(user)))
                elif cmd == "register":
                    self.swag.register(user)
                    self.msg(channel, "%s registered" % (user,))
                elif cmd == "buy":
                    try:
                        price = self.swag.buy(user, args[0], int(args[1]))
                        self.msg(channel, "%s: Your buy is in: %s shares of %s (price %s)" % (user, args[1], args[0], price))
                    except NoCashError, e:
                        self.msg(channel, str(e))
                    except LameError, e:
                        self.msg(channel, str(e))
                elif cmd == "sell":
                    try:
                        (shares, price) = self.swag.sell(user, args[0], args[1])
                        self.msg(channel, "%s: Your sale is in: you just cashed out %s shares of %s at $%s per share: $%s" % (user, shares, args[0], price, shares * price))
                    except NoSharesError, e:
                        self.msg(channel, str(e))
                    except LameError, e:
                        self.msg(channel, str(e))
            except Exception, e:
                self.msg(channel, "Bro, something broke: %s" % e)
                raise

class BotFactory(protocol.ClientFactory):
    def __init__(self, channel):
        self.channel = channel

    def buildProtocol(self, addr):
        p = YoloSwagBot()
        p.factory = self
        return p

    def clientConnectionLost(self, connector, reason):
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        reactor.stop()


if __name__ == '__main__':
    f = BotFactory("#ms7")
    reactor.connectSSL(sys.argv[1], int(sys.argv[2]), f, ssl.ClientContextFactory())
    reactor.run()
