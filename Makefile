PYTHON ?= python3
export PYTHONPATH := src
.PHONY: test evaluate check demo serve benchmark

test:
	$(PYTHON) -m unittest discover -s tests -v

evaluate:
	$(PYTHON) -m pipeline_watchdog evaluate

check: test evaluate
	$(PYTHON) -m compileall -q src tests
	node --check src/pipeline_watchdog/static/app.js

demo:
	$(PYTHON) -m pipeline_watchdog demo

serve:
	$(PYTHON) -m pipeline_watchdog serve

benchmark:
	$(PYTHON) scripts/benchmark.py
