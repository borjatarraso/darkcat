# SPDX-License-Identifier: BSD-3-Clause
# Convert the identity-generator markdown sources to txt / pdf / html.
#
# Requires `pandoc` on $PATH. PDF output additionally needs a LaTeX
# engine — `xelatex` is preferred (handles unicode in personas/bios);
# falls back to `pdflatex` if xelatex is unavailable.

SOURCES := $(wildcard 0*.md) README.md
BUILD   := build
TXT_DIR := $(BUILD)/txt
HTML_DIR:= $(BUILD)/html
PDF_DIR := $(BUILD)/pdf

TXT_OUT := $(patsubst %.md,$(TXT_DIR)/%.txt,$(SOURCES))
HTML_OUT:= $(patsubst %.md,$(HTML_DIR)/%.html,$(SOURCES))
PDF_OUT := $(patsubst %.md,$(PDF_DIR)/%.pdf,$(SOURCES))

PANDOC      ?= pandoc
PDF_ENGINE  ?= $(shell command -v xelatex >/dev/null 2>&1 && echo xelatex || echo pdflatex)

.PHONY: all txt html pdf clean
all: txt html pdf

txt:  $(TXT_OUT)
html: $(HTML_OUT)
pdf:  $(PDF_OUT)

$(TXT_DIR) $(HTML_DIR) $(PDF_DIR):
	@mkdir -p $@

$(TXT_DIR)/%.txt: %.md | $(TXT_DIR)
	$(PANDOC) -f gfm -t plain -o $@ $<

$(HTML_DIR)/%.html: %.md | $(HTML_DIR)
	$(PANDOC) -f gfm -t html5 --standalone --metadata title="$$(head -1 $< | sed 's/^# //')" -o $@ $<

$(PDF_DIR)/%.pdf: %.md | $(PDF_DIR)
	$(PANDOC) -f gfm -o $@ --pdf-engine=$(PDF_ENGINE) -V geometry:margin=1in $<

clean:
	rm -rf $(BUILD)
