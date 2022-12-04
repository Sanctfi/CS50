import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.security import check_password_hash, generate_password_hash
import datetime

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Create the new table for purchased stocks to be stored in - first checking if a table already exists
db.execute("CREATE TABLE IF NOT EXISTS portfolio (id INTEGER, userid INTEGER NOT NULL, symbol TEXT NOT NULL, name TEXT NOT NULL, shares NUMERIC NOT NULL, price NUMERIC NOT NULL, totalprice NUMERIC NOT NULL, PRIMARY KEY(id))")
# Create a table to store the history of each user - since the portfolio DB only will hold 1 row per stock and history needs
# full record of every purcahse and sale of stocks - capturing the timestamp on them
db.execute("CREATE TABLE IF NOT EXISTS history(id INTEGER, userid INTERGER NOT NULL, symbol TEXT NOT NULL, shares NUMERIC NOT NULL, price NUMERIC NOT NULL, timestamp TIMESTAMP NOT NULL, PRIMARY KEY(id))")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    user_data = db.execute("SELECT * FROM users WHERE id = ?", session["user_id"])
    # obtaining the accounts cash balance from the user db
    cash = user_data[0]['cash']

    # obtaining the stocks from the portofilio db
    portfolio = db.execute("SELECT * FROM portfolio WHERE userid = ?", session["user_id"])
    total = cash
    # loop through the portfolio to gather data and update the account total
    for stock in portfolio:
        price = lookup(stock['symbol'])['price']
        stock_price = stock['shares'] * price
        stock.update({'price': price, 'total': stock_price})
        total += stock_price

    # convert our raw ints into a USD format for both the cash(account) and total(all variables added)
    cash = usd(cash)
    total = usd(total)
    # sending through the portfilio to loop through and the values in USD form for cash and total to display directly
    return render_template("index.html", stocks=portfolio, cash=cash, total=total)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    # send them to a clean page if viewing page via Get
    if request.method == "GET":
        return render_template("buy.html")

    # if the page is refreshed via the form with Post
    if request.method == "POST":
        # collecting user_data from user table to collect their cash variable to verify sufficient funds - if not produce error
        user_data = db.execute("SELECT * FROM users WHERE id = ?", session["user_id"])

        # collecting the response from the API for that symbol - using this to collect name and current price
        response = lookup(request.form.get("symbol"))
        # looks at the db for an entry for this symbol - this is used to see if it should update or make a new entry if none exists
        # validate users input on the purchase form
        if not request.form.get("symbol"):
            return apology("Must enter stock symbol", 400)
        if not request.form.get("shares"):
            return apology("Must enter amount of shares", 400)
        # checks if response has returned none, if so then it means the look up was unsuccessful due to invalid symbol
        if response == None:
            return apology("Please enter a valid symbol", 400)
        # using regular expression to check to see if any special characters were entered in the stocks symbol field
        # this is needed to avoid any SQL injections that might be attempted
        special_check = request.form.get("symbol")
        if set("[@_!#$%^&*()<>?/\|}{~:];-'").intersection(special_check):
            return apology("Stock cannot contain special characters", 400)

        # setting up variables to input into table - easier to examine them below than in the execute line directly
        userid = session["user_id"]
        symbol = response["symbol"]
        name = response["name"]
        shares = request.form.get("shares")
        cash = user_data[0]["cash"]
        # checks if the shares value is a digit. Unsure why the numeric and min 1 functions on the page weren't enough but this seals up the last cases
        if not shares.isdigit():
            return apology("You cannot purchase partial shares.")
        price = response["price"]
        total_price = price * float(shares)
        new_balance = int(cash) - total_price
        # uses datetime.datetime.now() that captures the info in yyyy/mm/dd hh:mm:ss format
        current_time = datetime.datetime.now()

        stock_data = db.execute("SELECT * FROM portfolio WHERE userid=? AND name=?", session["user_id"], name)
        # checks the users balance against the total purchase amoun to ensure sufficient funds
        if user_data[0]["cash"] < total_price:
            return apology("Insufficient funds for purchase")
        # the try/except block below will check if the share amount is a whole number or not and return error if not
        # the try block only makes sure it can convert the string into an int, if it has a decimal, it will be unable
        try:
            shares_check = int(request.form.get("shares"))
        except ValueError:
            return apology("Shares must be in whole numbers")

        # looks to see if there is any data that came from the db - if not then it makes a new entry
        if not stock_data:
            # looks into the user list and updates that users account balance to the new total after purchase
            # creates a new row in the portofilio adding in the purchase variables
            db.execute("UPDATE users SET cash = ? WHERE id = ?", new_balance, userid)
            db.execute("INSERT INTO portfolio (userid, symbol, name, shares, price, totalprice) VALUES(?, ?, ?, ?, ?, ?)",
                        userid, symbol, name, shares, price, total_price)
            # creats a new row in history to log this sale
            db.execute("INSERT INTO history (userid, symbol, shares, price, timestamp) VALUES(?, ?, ?, ?, ?)",
                        userid, symbol, shares, price, current_time)
            return redirect("/")
        else:
            db.execute("UPDATE users SET cash = ? WHERE id = ?", new_balance, userid)
            # updates the existing row in the portofilio and adds the new shares to it
            current_shares = stock_data[0]["shares"]
            new_share_total = current_shares + int(shares)
            db.execute("UPDATE portfolio SET shares = ? AND totalprice = ? WHERE userid=? AND name=?",
                        new_share_total, price * int(new_share_total), userid, name)
            # insert a new row into the history db to log this purchase of the additional stocks
            db.execute("INSERT INTO history (userid, symbol, shares, price, timestamp) VALUES(?, ?, ?, ?, ?)",
                        userid, symbol, shares, price, current_time)
            return redirect("/")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    history = db.execute("SELECT * FROM history WHERE userid = ?", session["user_id"])
    return render_template("history.html", history=history)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    # if they arrive via url, direct them to the page with the stock symbol entry request page
    if request.method == "GET":
        return render_template("quote.html")
    # logic that runs when they use the form from the page above to provide a stock ticker to search for
    else:
        # checks to make sure there is text in the object for the symbol
        if not request.form.get("symbol"):
            return apology("Must enter stock ID", 400)
        # performs lookup on the symbol they entered, if it's None(null) after look up then it's not valid
        # if it is valid, we can route them to the quoted page where the stock is displayed with the companys stock info passed in as "result"
        result = lookup(request.form.get("symbol"))
        if result == None:
            return apology("Stock symbol is not valid")
        else:
            return render_template("quoted.html", result=result)


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("Must provide username", 400)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("Must provide password", 400)

        username = request.form.get("username")
        password = request.form.get("password")
        password_confirmed = request.form.get("confirmation")
        # Checks if the username is already in the DB and if the 2 passwords match
        if len(db.execute('SELECT username FROM users WHERE username = ?', username)) > 0:
            return apology("Username already in use", 400)
        elif password != password_confirmed:
            return apology("Password fields must match", 400)
        # If the account passes above checks, it's added to the database with the pass being hashed and sets the users session ID
        else:
            db.execute("INSERT INTO users (username, hash) VALUES(?, ?)", username, generate_password_hash(password))
            userrow = db.execute("SELECT * FROM users WHERE username = ?", username)
            session["id"] = userrow[0]["id"]
            return redirect("/")

    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    userid = session["user_id"]
    portfolio = db.execute("SELECT * FROM portfolio WHERE userid = ?", userid)
    user_data = db.execute("SELECT * FROM users WHERE id = ?", session["user_id"])
    symbol = request.form.get("symbol")

    if request.method == "POST":
        # checks if they didn't select a stock from the dropdown
        if not request.form.get("symbol"):
            return apology("Must select a stock to sell", 400)
        # the try/except block below will check if the share amount is a whole number or not and return error if not
        # the try block only makes sure it can convert the string into an int, if it has a decimal, it will be unable
        try:
            shares_check = int(request.form.get("shares"))
        except ValueError:
            return apology("Shares must be in whole numbers", 400)
        # collecting values to use in checks and functions
        requested_shares = int(request.form.get("shares"))
        requested_symbol = request.form.get("symbol")

        current_shares = db.execute("SELECT * FROM portfolio WHERE userid = ? AND symbol = ?", userid, requested_symbol)
        # checks if the requested shares amount exceeds the current count
        if current_shares[0]["shares"] < requested_shares:
            return apology("Insufficient shares to sell", 400)

        # performs the task of looking up the stocks current price, multiplying it by the amount of shares sold and adding the amount back to the users cash
        new_share_total = current_shares[0]["shares"] - requested_shares
        stock_price = lookup(requested_symbol)['price']
        sale_total = stock_price * requested_shares

        new_price_total = current_shares[0]["totalprice"] - sale_total

        new_cash_total = user_data[0]['cash'] + sale_total
        db.execute("UPDATE users SET cash=? WHERE id=?", new_cash_total, userid)
        # gets the new value of the current shares minus the new request and then sets the value of shares in DB to updated value
        db.execute("UPDATE portfolio SET shares=? WHERE userid = ? AND symbol = ?",  new_share_total, userid, requested_symbol)
        db.execute("UPDATE portfolio SET totalprice=? WHERE userid = ? AND symbol = ?",  new_price_total, userid, requested_symbol)

        # converts the sale amount to a negative number for the history page to reflect a sale vs purchase
        sold_shares = requested_shares * -1
        # captures the timestamp for this transaction
        current_time = datetime.datetime.now()
        # inserts into the history DB a row for logging the sale of this stock

        db.execute("INSERT INTO history (userid, symbol, shares, price, timestamp) VALUES(?, ?, ?, ?, ?)",
                    userid, symbol, sold_shares, stock_price, current_time)

        # updated fetch for this stock, if the shares value is 0 then delete it from the DB so it's removed from the list after redirect
        zero_shares_check = db.execute("SELECT shares FROM portfolio WHERE userid=? AND symbol=?", userid, requested_symbol)
        if zero_shares_check[0]["shares"] == 0:
            db.execute("DELETE FROM portfolio WHERE userid=? AND symbol=?", userid, requested_symbol)
        return redirect("/")

    if request.method == "GET":
        return render_template("sell.html", stocks=portfolio)


@app.route("/funds", methods=["GET", "POST"])
def funds():
    if request.method == "POST":
        # collects the users session id
        userid = session["user_id"]
        # obtaining the accounts cash balance from the user db
        user_data = db.execute("SELECT * FROM users WHERE id = ?", session["user_id"])
        cash = user_data[0]['cash']
        if cash < 0:
            return apology("Must enter a value greater than 0")
        # obtain the user entered amount of funds
        additional_funds = int(request.form.get("funds"))

        db.execute("UPDATE users SET cash=? where id=?", cash+additional_funds, userid)
        return redirect("/")

    if request.method == "GET":
        return render_template("funds.html")