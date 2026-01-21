# SQL Magic: %%duckdb and %%sql

Write native SQL queries directly in notebook cells - no Python string wrapping needed.

## The Problem

Data Scientists often think in SQL, but Jupyter forces them to write:

```python
# The old way - SQL wrapped in Python strings 😔
result = pd.read_sql("""
    SELECT region, SUM(revenue) as total
    FROM sales
    GROUP BY region
""", connection)
```

## The Solution: Cell Magics

With MCP Jupyter, you can write pure SQL:

```sql
%%duckdb
SELECT region, SUM(revenue) as total
FROM sales
GROUP BY region
```

No quotes. No escaping. Just SQL.

## How It Works

### Automatic DataFrame Discovery

When you run a `%%duckdb` cell, the magic:

1. **Scans your namespace** for all pandas/polars DataFrames
2. **Registers them** as DuckDB virtual tables
3. **Executes your SQL** against those tables
4. **Returns results** as a new DataFrame

```python
# Cell 1: Create DataFrames (normal Python)
import pandas as pd

customers = pd.DataFrame({
    "id": [1, 2, 3],
    "name": ["Alice", "Bob", "Charlie"]
})

orders = pd.DataFrame({
    "customer_id": [1, 1, 2, 3],
    "amount": [100, 150, 200, 50]
})
```

```sql
-- Cell 2: Join them with SQL!
%%duckdb
SELECT c.name, SUM(o.amount) as total_spent
FROM customers c
JOIN orders o ON c.id = o.customer_id
GROUP BY c.name
ORDER BY total_spent DESC
```

**Output:**

| name    | total_spent |
|---------|-------------|
| Bob     | 200         |
| Alice   | 250         |
| Charlie | 50          |

## %%sql Alias

If you prefer, `%%sql` is an alias for `%%duckdb`:

```sql
%%sql
SELECT * FROM sales WHERE revenue > 10000
```

## Advanced Usage

### Parameters (Coming Soon)

```sql
%%duckdb --param threshold=10000
SELECT * FROM sales WHERE revenue > $threshold
```

### Save Results

```python
# Get the result as a DataFrame
result = %duckdb SELECT COUNT(*) FROM sales
print(f"Total rows: {result.iloc[0, 0]}")
```

### Complex Queries

DuckDB supports modern SQL features:

```sql
%%duckdb
WITH monthly_totals AS (
    SELECT 
        DATE_TRUNC('month', order_date) as month,
        SUM(amount) as total
    FROM orders
    GROUP BY 1
)
SELECT 
    month,
    total,
    total - LAG(total) OVER (ORDER BY month) as change
FROM monthly_totals
ORDER BY month
```

## Performance

DuckDB reads directly from pandas memory - no copying required. This makes it blazingly fast even on large DataFrames:

| Rows | Query Time |
|------|-----------|
| 1M   | ~100ms    |
| 10M  | ~500ms    |
| 100M | ~3s       |

## Installation

The SQL magic is automatically available when your kernel starts. It requires `duckdb` to be installed:

```bash
pip install duckdb
```

Or install with the superpowers bundle:

```bash
pip install "mcp-server-jupyter[superpowers]"
```

## Troubleshooting

### "NameError: name 'duckdb' is not defined"

DuckDB isn't installed. Run:

```python
!pip install duckdb
```

Then restart the kernel.

### "Table 'my_df' not found"

Make sure your DataFrame variable:

1. Is defined in the same kernel session
2. Has a valid Python identifier name
3. Is a pandas or polars DataFrame

### "Magic not found"

The kernel might not have started properly. Try:

1. `Ctrl+Shift+P` → "MCP Jupyter: Restart Server"
2. Re-run your first cell

## See Also

- [Quick Start](../getting-started/quickstart.md) - Get up and running
- [Asset Rendering](./asset-rendering.md) - How plots are displayed
- [DuckDB Documentation](https://duckdb.org/docs/) - Full SQL reference
