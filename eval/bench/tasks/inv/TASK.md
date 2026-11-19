Build the package `inv/` (with an empty-compatible `inv/__init__.py`) as THREE independent modules a team could write in parallel, then make the integration test pass.

inv/parse.py:  `parse_lines(text) -> list[dict]`  each non-blank, non-'#' line is "sku,qty,price" -> {"sku": str, "qty": int, "price": float}; a malformed line raises ValueError whose message contains its 1-based line number.
inv/price.py:  `total(items) -> float` = round(sum(qty*price), 2);  `apply_discount(amount, pct) -> float` = round(amount*(1-pct/100), 2), pct outside 0..100 raises ValueError.
inv/report.py: `render(items, discount_pct=0) -> str` (uses inv.price): one line per item "SKU xQTY @ PRICE = LINE_TOTAL" (price and line total with 2 decimals), then "TOTAL: X.XX" after the discount.

Do not modify test_inv.py. Run: python3 -m pytest -q test_inv.py
