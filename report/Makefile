PYTHON ?= python3
LATEXMK ?= latexmk

.PHONY: all agentic figures agentic-figures tables clean

all:
	$(LATEXMK) -pdf -synctex=1 -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build main.tex

agentic:
	cd agentic && $(LATEXMK) -pdf -synctex=1 -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build main.tex

agentic-figures:
	mkdir -p agentic/images build/matplotlib
	MPLCONFIGDIR="$(CURDIR)/build/matplotlib" $(PYTHON) analysis/agentic_figures.py --data data/agentic-campaign.json --output-dir agentic/images

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
