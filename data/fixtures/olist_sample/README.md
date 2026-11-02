# Olist sample (CI fixture)

A small, deterministic subset of the Olist e-commerce data, committed so that CI's
`dbt-build-local` job can run a real `dbt build` without the 124 MB raw dataset
(`docs/local-stack-scope.md` §6.5).

**Contents:** every order purchased on or after 2018-08-01 (6,532 orders), plus every row they
reference: their order items, payments and customers, the products and sellers on those items,
and the full category translation table. That's 32,749 rows and about 3.5 MB. Lines are copied
byte for byte from the original CSVs, in source order.

**Regenerate** (from a checkout with the full data in `data/raw/`):

```bash
python -m ingestion.make_olist_sample      # rewrites this folder's CSVs; output is identical every run
```

**Use locally:**

```bash
python -m ingestion.load_local --raw-dir data/fixtures/olist_sample --warehouse-path /tmp/sample.duckdb
cd dbt_project && WAREHOUSE_PATH=/tmp/sample.duckdb dbt build --target local --profiles-dir .
```

## Attribution and license

Source: **Brazilian E-Commerce Public Dataset by Olist**, published by Olist on Kaggle,
<https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce>.

License: **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International
(CC BY-NC-SA 4.0)**, <https://creativecommons.org/licenses/by-nc-sa/4.0/>. The license was checked
against Kaggle's dataset metadata on 2026-11-02.

Changes made: rows filtered as described above; no values edited. Because of the ShareAlike term,
this sample is distributed under the same CC BY-NC-SA 4.0 license, separately from the rest of
the repository. It's used here for non-commercial, educational purposes only.
