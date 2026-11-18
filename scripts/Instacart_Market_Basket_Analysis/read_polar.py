import polars as pl
aisles = pl.read_csv("aisles.csv")
departments = pl.read_csv("departments.csv")
order_products__prior = pl.read_csv("order_products__prior.csv")
order_products__train = pl.read_csv("order_products__train.csv")
orders = pl.read_csv("orders.csv")
products = pl.read_csv("products.csv")

print(aisles.head())
print(departments.head()) 
print(order_products__prior.head()) 
print(order_products__train.head()) 
print(orders.head())
print(products.head())
