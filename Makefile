# Makefile for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: January 17, 2016
# URL: https://github.com/paylogic/pip-accel

WORKON_HOME ?= $(HOME)/.virtualenvs
VIRTUAL_ENV ?= $(WORKON_HOME)/pip-accel
PATH := $(VIRTUAL_ENV)/bin:$(PATH)
SHELL = /bin/bash

default:
	@echo 'Makefile for the pip accelerator'
	@echo
	@echo 'Usage:'
	@echo
	@echo '    make install    install the package in a virtual environment'
	@echo '    make reset      recreate the virtual environment'
	@echo '    make test       run the tests and collect coverage'
	@echo '    make check      check the coding style'
	@echo '    make docs       update documentation using Sphinx'
	@echo '    make publish    publish changes to GitHub/PyPI'
	@echo '    make clean      cleanup all temporary files'
	@echo

install:
	test -d "$(VIRTUAL_ENV)" || mkdir -p "$(VIRTUAL_ENV)"
	test -x "$(VIRTUAL_ENV)/bin/python" || virtualenv "$(VIRTUAL_ENV)"
	test -x "$(VIRTUAL_ENV)/bin/pip" || easy_install pip
	pip uninstall --yes --quiet pip-accel &>/dev/null || true
	pip install --quiet --editable .
	pip-accel install --quiet --requirement=requirements-testing.txt

reset:
	rm -Rf "$(VIRTUAL_ENV)"
	make --no-print-directory clean install

test: install
	scripts/prepare-test-environment.sh
	scripts/collect-test-coverage.sh
	coverage html

tox: install
	(test -x "$(VIRTUAL_ENV)/bin/tox" \
		|| pip-accel install --quiet tox) \
		&& tox

detox: install
	(test -x "$(VIRTUAL_ENV)/bin/detox" \
		|| pip-accel install --quiet detox) \
		&& COVERAGE=no detox

check: install
	(test -x "$(VIRTUAL_ENV)/bin/flake8" \
		|| pip-accel install --quiet --requirement requirements-flake8.txt) \
		&& flake8

docs: install
	test -x "$(VIRTUAL_ENV)/bin/sphinx-build" || pip-accel install --quiet sphinx
	cd docs && sphinx-build -b html -d build/doctrees . build/html

publish: install
	git push origin && git push --tags origin
	test -x "$(VIRTUAL_ENV)/bin/twine" || pip-accel install --quiet twine
	make clean && python setup.py sdist && twine upload dist/*

clean:
	rm -Rf \
		*.egg \
		.cache/ \
		.coverage \
		.coverage.* \
		.tox/ \
		build/ \
		dist/ \
		docs/build/ \
		htmlcov/
	find -name __pycache__ -exec rm -Rf {} \; &>/dev/null || true
	find -type f -name '*.py[co]' -delete

.PHONY: default install reset test tox detox check docs publish clean
