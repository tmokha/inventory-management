"""
Mock data for the Factory Inventory Management System
This module loads sample data from JSON files for inventory items, orders, demand forecasts, and backlog items.
All data is from September 2025 and includes warehouse, category, and date fields for filtering.
"""

import json
import os

# Get the directory where this file is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')

def load_json_file(filename):
    """Load data from a JSON file in the data directory"""
    filepath = os.path.join(DATA_DIR, filename)
    with open(filepath, 'r') as f:
        return json.load(f)

# Load all datasets from JSON files
inventory_items = load_json_file('inventory.json')
orders = load_json_file('orders.json')
demand_forecasts = load_json_file('demand_forecasts.json')
backlog_items = load_json_file('backlog_items.json')

# Load spending data
spending_data = load_json_file('spending.json')
spending_summary = spending_data['spending_summary']
monthly_spending = spending_data['monthly_spending']
category_spending = spending_data['category_spending']

# Load transactions
recent_transactions = load_json_file('transactions.json')

# Load purchase orders
purchase_orders = load_json_file('purchase_orders.json')

# Restocking orders are created at runtime and persisted to disk. The file is
# gitignored and may not exist yet, so start from an empty list in that case.
RESTOCKING_ORDERS_FILE = 'restocking_orders.json'

def load_restocking_orders():
    """Load submitted restocking orders, or an empty list if none exist yet"""
    if not os.path.exists(os.path.join(DATA_DIR, RESTOCKING_ORDERS_FILE)):
        return []
    return load_json_file(RESTOCKING_ORDERS_FILE)

def save_restocking_orders(orders):
    """Write restocking orders back to disk so they survive server restarts"""
    # DATA_DIR is resolved at call time so tests can redirect writes to a temp dir
    filepath = os.path.join(DATA_DIR, RESTOCKING_ORDERS_FILE)
    with open(filepath, 'w') as f:
        json.dump(orders, f, indent=2)

restocking_orders = load_restocking_orders()

# All data is now loaded from JSON files in the data/ directory
# This allows for easier maintenance and updates of the sample data
