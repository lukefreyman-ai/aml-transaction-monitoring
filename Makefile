PY ?= .venv/bin/python

.PHONY: setup run quick test notebook clean

setup:            ## create venv + install deps
	python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt

run:              ## generate 500k+ synthetic transactions, run 8 rules, score, tune, write results/
	$(PY) run.py

quick:            ## small run (60k rows, 400 customers), no tuning
	$(PY) run.py --rows 60000 --customers 400 --skip-tuning --out results_quick

test:
	$(PY) -m pytest -q

notebook:         ## build + execute notebooks/alerts_analysis.ipynb from results/
	$(PY) notebooks/build_notebook.py && .venv/bin/jupyter nbconvert --to notebook --execute --inplace notebooks/alerts_analysis.ipynb

clean:
	rm -rf results_quick .pytest_cache
