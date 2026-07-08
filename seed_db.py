"""
Creates a small demo SQLite database so QueryPilot AI has something real
to query the moment you clone the repo. Swap DB_PATH in .env to point at
your own PostgreSQL/SQLite/MySQL database once you're ready -- the agent
code doesn't care, it only talks to app/database.py.

Run: python seed_db.py
"""
import sqlite3
import random
from datetime import date, timedelta
import os

DB_PATH = os.getenv("DB_PATH", "data/querypilot.db")
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

random.seed(42)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.executescript("""
DROP TABLE IF EXISTS invoices;
DROP TABLE IF EXISTS sales;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS campaigns;

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    customer_name TEXT NOT NULL,
    region TEXT NOT NULL,           -- North America / Europe / APAC
    segment TEXT NOT NULL,          -- Enterprise / SMB
    signup_date TEXT NOT NULL,
    churned INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE sales (
    sale_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    sale_date TEXT NOT NULL,
    product TEXT NOT NULL,
    sales_amount REAL NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE invoices (
    invoice_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    invoice_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    invoice_amount REAL NOT NULL,
    paid INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE campaigns (
    campaign_id INTEGER PRIMARY KEY,
    campaign_name TEXT NOT NULL,
    channel TEXT NOT NULL,          -- Search / Social / Display
    month TEXT NOT NULL,            -- 'YYYY-MM'
    spend REAL NOT NULL,
    revenue_attributed REAL NOT NULL
);
""")

regions = ["North America", "Europe", "APAC"]
segments = ["Enterprise", "SMB"]
products = ["Core Platform", "Analytics Add-on", "Premium Support", "API Access"]
channels = ["Search", "Social", "Display"]

# customers
customers = []
for i in range(1, 41):
    signup = date(2024, 1, 1) + timedelta(days=random.randint(0, 500))
    churned = 1 if random.random() < 0.15 else 0
    customers.append((i, f"Customer {i:02d}", random.choice(regions),
                       random.choice(segments), signup.isoformat(), churned))
cur.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", customers)

# sales across 2025 with a Q2 bump for realism
sale_id = 1
sales = []
for month in range(1, 13):
    n_sales = random.randint(15, 30)
    boost = 1.3 if month in (4, 5, 6) else 1.0
    for _ in range(n_sales):
        cust = random.randint(1, 40)
        day = random.randint(1, 28)
        amount = round(random.uniform(500, 8000) * boost, 2)
        sales.append((sale_id, cust, date(2025, month, day).isoformat(),
                       random.choice(products), amount))
        sale_id += 1
cur.executemany("INSERT INTO sales VALUES (?,?,?,?,?)", sales)

# invoices, some overdue/unpaid
invoice_id = 1
invoices = []
for cust in range(1, 41):
    for _ in range(random.randint(1, 4)):
        idate = date(2025, random.randint(1, 12), random.randint(1, 28))
        due = idate + timedelta(days=30)
        amount = round(random.uniform(300, 5000), 2)
        paid = 0 if (due < date(2025, 12, 1) and random.random() < 0.2) else 1
        invoices.append((invoice_id, cust, idate.isoformat(), due.isoformat(), amount, paid))
        invoice_id += 1
cur.executemany("INSERT INTO invoices VALUES (?,?,?,?,?,?)", invoices)

# campaigns
campaign_id = 1
campaigns = []
for month in range(1, 13):
    for channel in channels:
        spend = round(random.uniform(2000, 15000), 2)
        roas = random.uniform(1.5, 4.5)
        campaigns.append((campaign_id, f"{channel} Campaign {month:02d}", channel,
                           f"2025-{month:02d}", spend, round(spend * roas, 2)))
        campaign_id += 1
cur.executemany("INSERT INTO campaigns VALUES (?,?,?,?,?,?)", campaigns)

conn.commit()
conn.close()

print(f"Demo database created at {DB_PATH}")
print("Tables: customers, sales, invoices, campaigns")
