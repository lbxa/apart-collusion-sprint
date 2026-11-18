PYTHON ?= python3
LATEXMK ?= latexmk
COLLECTION_DATA ?= data/collusion-progress-final-20261117

.PHONY: all agentic agentic-historical agentic-status-figure agentic-pilot-table agentic-collection-figures figures agentic-figures tables clean

all:
	$(LATEXMK) -pdf -synctex=1 -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build main.tex

agentic:
	cd agentic && $(LATEXMK) -pdf -synctex=1 -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build main.tex

agentic-historical:
	cd agentic && $(LATEXMK) -pdf -synctex=1 -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build/historical historical-october-main.tex

agentic-figures:
	mkdir -p agentic/images build/matplotlib
	MPLCONFIGDIR="$(CURDIR)/build/matplotlib" $(PYTHON) analysis/agentic_figures.py --data data/agentic-campaign.json --output-dir agentic/images

agentic-status-figure:
	mkdir -p agentic/images build/matplotlib
	MPLCONFIGDIR="$(CURDIR)/build/matplotlib" $(PYTHON) analysis/resistance_figures.py --data data/collusion-resistance-pending-20261117.json --output-dir agentic/images --collection-not-started

agentic-pilot-table:
	mkdir -p agentic/tables build/matplotlib
	MPLCONFIGDIR="$(CURDIR)/build/matplotlib" $(PYTHON) analysis/pilot_tables.py --data-dir data/collusion-pilots-20261117/v2 --expected-seed 700 --require-complete-cohort --output agentic/tables/pilot-v2.tex
	MPLCONFIGDIR="$(CURDIR)/build/matplotlib" $(PYTHON) analysis/pilot_tables.py --data-dir data/collusion-pilots-20261117/v3 --expected-seed 800 --require-complete-cohort --output agentic/tables/pilot-v3.tex

agentic-collection-figures:
	mkdir -p agentic/images agentic/tables build/matplotlib
	MPLCONFIGDIR="$(CURDIR)/build/matplotlib" $(PYTHON) analysis/progress_figures.py --data-dir $(COLLECTION_DATA) --output-dir agentic/images --table-dir agentic/tables

figures:
	mkdir -p figures build/matplotlib
	MPLCONFIGDIR="$(CURDIR)/build/matplotlib" $(PYTHON) analysis/baseline_figures.py --data data/baseline-smoke.json --output-dir figures

tables:
	mkdir -p tables
	$(PYTHON) analysis/probe_snapshot.py
	$(PYTHON) analysis/model_benchmark.py

clean:
	$(LATEXMK) -C -outdir=build main.tex
	$(LATEXMK) -C main.tex
