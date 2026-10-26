PYTHON ?= python3
LATEXMK ?= latexmk

.PHONY: all figures clean

all:
	$(LATEXMK) -pdf -synctex=1 -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build main.tex

figures:
	mkdir -p figures build/matplotlib
	MPLCONFIGDIR="$(CURDIR)/build/matplotlib" $(PYTHON) analysis/baseline_figures.py --data data/baseline-smoke.json --output-dir figures

clean:
	$(LATEXMK) -C -outdir=build main.tex
	$(LATEXMK) -C main.tex
