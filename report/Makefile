PYTHON ?= python3
LATEXMK ?= latexmk

.PHONY: all figures clean

all: figures
	$(LATEXMK) -pdf -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build main.tex

figures:
	mkdir -p build/figures build/matplotlib
	MPLCONFIGDIR="$(CURDIR)/build/matplotlib" $(PYTHON) ../docs/reporting/templates/figure-example.py --output-dir build/figures

clean:
	$(LATEXMK) -C -outdir=build main.tex
