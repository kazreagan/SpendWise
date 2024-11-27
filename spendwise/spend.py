import os
from dotenv import load_dotenv
import pyaudio
import mysql.connector
from datetime import datetime, timedelta
import requests
import speech_recognition as sr


###database connection and setup
def connect_to_db():
    """connect to MySQL Database"""
    try:
        db = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME")
        )
        print("Database conection established successfully!")
        return db
    except mysql.connector.Error as err:
        print(f"Error: {err}")
        return None

def setup_tables():
    """Create necessary tables in the database."""
    db = connect_to_db()
    if not db:
        return

    cursor = db.cursor()

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255),
                email VARCHAR(255) UNIQUE
            );
        """)
    except mysql.connector.Error as err:
        print(f"Database error while creating users table: {err}")

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                expense_id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT,
                description VARCHAR(255),
                amount DECIMAL(10, 2),
                date DATETIME
            );
        """)
    except mysql.connector.Error as err:
        print(f"Database error while creating Expenses table: {err}")

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                summary_id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT,
                period_type ENUM('daily', 'weekly', 'monthly'),
                total_amount DECIMAL(10, 2),
                start_date DATE,
                end_date DATE,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
        """)
    except mysql.connector.Error as err:
        print(f"Database error while creating summaries table: {err}")

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stockdata (
                stock_id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255),
                performance DECIMAL(10, 2),
                timestamp DATE
            );
        """)
    except mysql.connector.Error as err:
        print(f"Database error while creating stockdata table: {err}")

    db.commit()
    cursor.close()
    db.close()
    print("Database tables created successfully!")


#initialize the database setup
setup_tables()


#parsing logic
def parse_expense_details(text):
    words = text.split()
    amount = None
    description = None

    #extract the first number as amount
    for word in words:
        try:
            amount = float(word)
            break
        except ValueError:
            continue
    if amount:
        #assuming the rest of the sentence is the description
        description_start = words.index(word) + 1
        description = " ".join(words[description_start:])

    if not amount or not description:
        raise ValueError("could not parse expense details from the text.")
    
    return description, amount

#voice-to-text for expense logging
def log_expense_from_voice(user_id):
    recognizer = sr.Recognizer()

    try:
        with sr.Microphone() as source:
            print("Listening for expense details...")
            audio = recognizer.listen(source)

        text = recognizer.recognize_google(audio)
        print(f"Recognized text: {text}")

        description, amount = parse_expense_details(text)

        db = connect_to_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO expenses (user_id, description, amount, date)
            VALUES (%s, %s, %s, NOW());
        """, (user_id, description, amount))
        db.commit()

        print(f"Logged expense: {description} - ${amount}")
    except Exception as e:
        print(f"Error recognizing or logging expense: {e}")
    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()

###generate summaries
def generate_summary(user_id, period='daily'):
    ###generate a summary of expenses over a specified period (daily)###
    db = connect_to_db()
    cursor = db.cursor()

    #set date range based on the period type
    today = datetime.today().date()
    if period == 'daily':
        start_date, end_date = today, today
    elif period == 'weekly':
        start_date, end_date = today - timedelta(days=7), today
    elif period == 'monthly':
        start_date, end_date = today - timedelta(days=30), today

    #calculate total expenses within the date range
    try:
        
        cursor.execute("""
            SELECT SUM(amount) FROM Expenses
            WHERE user_id = %s AND date BETWEEN %s AND %s;
        """, (user_id, start_date, end_date))
        total_amount = cursor.fetchone()[0] or 0.0
    except mysql.connector.Error as err:
        print(f"Database error while fetching expenses: {err}")
        total_amount = 0.0

    try:
        # Insert summary into the summaries table
        cursor.execute("""
            INSERT INTO summaries (user_id, period_type, total_amount, start_date, end_date)
            VALUES (%s, %s, %s, %s, %s);
        """, (user_id, period, total_amount, start_date, end_date))
        db.commit()
    except mysql.connector.Error as err:
        print(f"Database error while inserting summary: {err}")

###fetch stock market data
def fetch_stock_data():
    """Fetch top-performing stock data from Alpha Vantage and store it in the stockdata table."""
    db = connect_to_db()
    cursor = None
    if db:
        cursor = db.cursor()

    try:
        # API details
        api_key = "YOUR_API_KEY"
        base_url = "https://www.alphavantage.co/query"
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": "APPL",  # Replace with the desired stock symbol
            "apikey": api_key
        }
        
        # Make the API request
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        data = response.json()
        
        # Process and store stock data
        if "Time Series (Daily)" in data:
            stock_data = data["Time Series (Daily)"]
            for date, details in stock_data.items():
                try:
                    # Extract and calculate stock performance
                    open_price = float(details["1. open"])
                    close_price = float(details["4. close"])
                    performance = close_price - open_price

                    # Insert into the database
                    cursor.execute("""
                        INSERT INTO stockdata (name, performance, timestamp)
                        VALUES (%s, %s, %s);
                    """, ("IBM", performance, date))
                    db.commit()
                except mysql.connector.Error as err:
                    print(f"Database error while inserting stock data for {date}: {err}")
            print("Stock data fetched and stored successfully!")
        else:
            print("Unexpected response format:", data)

    except requests.exceptions.RequestException as e:
        print(f"Error fetching stock data: {e}")
    except Exception as general_error:
        print(f"An unexpected error occurred: {general_error}")
    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


###main execution example
if __name__ == "__main__":
    #example setup for a single user (to be replaced with actual user management)
    user_id = 1  #assumed to exist in the database

    #log an expense by voice
    log_expense_from_voice(user_id)

    #generate expense summaries
    generate_summary(user_id, period='daily')
    generate_summary(user_id, period='weekly')
    generate_summary(user_id, period='monthly')

    #fetch and update stock market data
    fetch_stock_data()