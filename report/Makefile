PYTHON ?= python3
LATEXMK ?= latexmk

.PHONY: all figures clean

all:
	$(LATEXMK) -pdf -synctex=1 -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build main.tex

figures:
	mkdir -p figures build/figures build/matplotlib
	MPLCONFIGDIR="$(CURDIR)/build/matplotlib" $(PYTHON) ../docs/reporting/templates/figure-example.py --output-dir build/figures
	cp build/figures/figure-example.pdf figures/figure-example.pdf

clean:
	$(LATEXMK) -C -outdir=build main.tex
	$(LATEXMK) -C main.tex
