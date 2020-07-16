import os

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    # Query the user's transactions
    rows = db.execute("SELECT * FROM transactions WHERE userID=:id", id=session["user_id"])
    table = {}
    total = 0
    for row in rows:
        # If the symbol is not found in the table, create a new dictionary
        if row["symbol"] not in table:
            row_dict = {}
            # Get the symbol and quantity from the query
            row_dict["symbol"] = row["symbol"]
            row_dict["shares"] = int(row["quantity"])

            # Look up the symbol and store the resulting information in the dictionary
            quote_lookup = lookup(row["symbol"])
            row_dict["name"] = quote_lookup["name"]
            row_dict["price"] = quote_lookup["price"]
            # Calculate the total and store it in the dictionary
            row_dict["total"] = row_dict["shares"] * quote_lookup["price"]

            # Add to the total balance
            total += row_dict["total"]
            # Store the row's dictionary
            table[row["symbol"]] = row_dict
        # If the symbol is already in the dictionary
        else:
            # Add the quantity to the total shares for the stock
            table[row["symbol"]]["shares"] += int(row["quantity"])

            # Look up the symbol
            quote_lookup = lookup(row["symbol"])
            # Add to the entry's total
            table[row["symbol"]]["total"] += int(row["quantity"]) * quote_lookup["price"]
            # Add to the total balance
            total += int(row["quantity"]) * quote_lookup["price"]
    
    # Format the float prices for each stock
    for d in list(table.values())[:]:
        d["price"] = usd(d["price"])
        d["total"] = usd(d["total"])

        if d["shares"] <= 0:
            del table[d["symbol"]]
    
    # Get the user's cash and add it to the total balance
    user_row = db.execute("SELECT * FROM users WHERE id=:id", id=session["user_id"])[0]
    cash = user_row["cash"]
    total += cash

    # Return index.html with the table dictionary, cash, and total
    return render_template("index.html", table=table.values(), cash=usd(cash), total=usd(total))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "POST":
        # Get information from request form
        symbol, shares = request.form.get("symbol"), int(request.form.get("shares"))
        # Look up the given symbol
        symbol_quote = lookup(symbol)

        # Ensure that the symbol is valid and that the symbol is not blank
        if not symbol or symbol_quote is None:
            return apology("invalid symbol", 403)

        # Ensure that shares is not blank
        if not shares:
            return apology("invalid quantity", 403)
        
        # Get information about the user from the database
        user_row = db.execute("SELECT * FROM users WHERE id=:id", id=session["user_id"])[0]
        # Get the user's balance from the query
        user_cash = user_row["cash"]

        # Ensure that the user has enough cash to make the transaction
        if symbol_quote["price"] * shares > user_cash:
            return apology("not enough cash", 403)
        
        # Insert the transaction into the database
        db.execute("INSERT INTO transactions ('userID', 'symbol', 'quantity', 'timestamp', 'price') VALUES (:userID, :symbol, :quantity, datetime('now'), :price)", userID=session["user_id"], symbol=symbol, quantity=shares, price=symbol_quote["price"])
        # Update the user's cash
        db.execute("UPDATE users SET cash = :cash WHERE id = :id", cash=user_cash - (shares * symbol_quote["price"]), id=session["user_id"])

        # Redirect to /
        return redirect("/")

    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    # Get the user's transactions
    rows = db.execute("SELECT * FROM transactions WHERE userID=:id", id=session["user_id"])

    # Use them in history.html
    return render_template("history.html", rows=rows)


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
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

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
    """Get stock quote."""

    if request.method == "POST":
        # Look up the given symbol
        stock = lookup(request.form.get("symbol"))

        # Ensure that the symbol is valid
        if stock is None:
            return apology("invalid symbol", 403)
        
        # Display the stock's information
        return render_template("quoted.html", name=stock["name"], symbol=stock["symbol"], cost=usd(stock["price"]))

    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    if request.method == "POST":
        username, password, confirmation = request.form.get("username"), request.form.get("password"), request.form.get("confirmation")

        # Ensure username is not taken and that username is not blank
        rows = db.execute("SELECT * FROM users WHERE username = :username", username=username)
        if len(rows) != 0 or not username:
            return apology("invalid username", 403)
        
        # Ensure both passwords are not blank
        if not password or not confirmation:
            return apology("password is empty", 403)
        
        # Ensure that passwords match
        if password != confirmation:
            return apology("passwords do not match", 403)
        
        # Insert the new login information into the database
        db.execute("INSERT INTO users (username, hash) VALUES (:username, :hash)", username=username, hash=generate_password_hash(password))

        return redirect("/login")

    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if request.method == "POST":
        # Get info from the form
        symbol, shares = request.form.get("symbol"), int(request.form.get("shares"))

        # Ensure that the symbol field is not blank
        if not symbol:
            return apology("empty symbol", 403)
        # Ensure that the shares field is not blank
        if not shares:
            return apology("shares field is empty", 403)
        
        # Get the number of shares that the user owns and ensure that the user owns enough shares to sell
        count = db.execute("SELECT SUM(quantity) FROM transactions WHERE userID=:userID AND symbol=:symbol", userID=session["user_id"], symbol=symbol)[0]['SUM(quantity)']
        if shares > count:
            return apology("not enough shares", 403)

        # Look up symbol
        quote = lookup(symbol)
        
        # Create a new transaction in the sql table
        db.execute("INSERT INTO transactions ('userID', 'symbol', 'quantity', 'timestamp', 'price') VALUES (:userID, :symbol, :quantity, datetime('now'), :price)", userID=session["user_id"], symbol=symbol, quantity=-shares, price=quote["price"])
        
        # Add to the user's cash
        user_cash = db.execute("SELECT * FROM users WHERE id=:id", id=session["user_id"])[0]["cash"]
        user_cash += shares * quote["price"]
        # Edit the user's cash in the users table
        db.execute("UPDATE users SET cash=:cash WHERE id=:id", cash=user_cash, id=session["user_id"])
        
        # Redirect the user to index.html
        return redirect("/")

    else:
        # Get every different stock the user owns to show in the dropdown
        rows = db.execute("SELECT * FROM transactions WHERE userID=:id GROUP BY symbol", id=session["user_id"])
        return render_template("sell.html", rows=rows)



def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
