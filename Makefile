# Makefile for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: October 31, 2015
# URL: https://github.com/paylogic/pip-accel

WORKON_HOME ?= $(HOME)/.virtualenvs
VIRTUAL_ENV ?= $(WORKON_HOME)/pip-accel
ACTIVATE = . "$(VIRTUAL_ENV)/bin/activate"
SHELL = /bin/bash

default:
	@echo 'Makefile for the pip accelerator'
	@echo
	@echo 'Usage:'
	@echo
	@echo '    make install    install the package in a virtual environment'
	@echo '    make reset      recreate the virtual environment'
	@echo '    make test       run the unit test suite'
	@echo '    make coverage   run the tests, report coverage'
	@echo '    make check      check the coding style'
	@echo '    make docs       update documentation using Sphinx'
	@echo '    make publish    publish changes to GitHub/PyPI'
	@echo '    make clean      cleanup all temporary files'
	@echo

install:
	test -d "$(VIRTUAL_ENV)" || mkdir -p "$(VIRTUAL_ENV)"
	test -x "$(VIRTUAL_ENV)/bin/python" || virtualenv "$(VIRTUAL_ENV)"
	test -x "$(VIRTUAL_ENV)/bin/pip" || ($(ACTIVATE) && easy_install pip)
	$(ACTIVATE) && pip uninstall --yes --quiet pip-accel || true
	$(ACTIVATE) && pip install --quiet --editable .
	$(ACTIVATE) && pip-accel install --quiet 'boto >= 2.32'

reset:
	rm -Rf "$(VIRTUAL_ENV)"
	make --no-print-directory clean install

test: install
	$(ACTIVATE) && pip-accel install --quiet -r requirements-testing.txt
	$(ACTIVATE) && detox -- -v

coverage: install
	test -x "$(VIRTUAL_ENV)/bin/coverage" || ($(ACTIVATE) && pip-accel install --quiet coverage)
	$(ACTIVATE) && scripts/collect-full-coverage.sh
	# Report coverage statistics on the command line.
	$(ACTIVATE) && coverage report
	# Generate an HTML report of coverage statistics.
	$(ACTIVATE) && coverage html
	# Exit with a nonzero status code when the coverage is less than 90%.
	$(ACTIVATE) && coverage report --fail-under=90 &>/dev/null

check: install
	test -x "$(VIRTUAL_ENV)/bin/flake8" || ($(ACTIVATE) && pip-accel install --quiet --requirement requirements-flake8.txt)
	flake8

docs: install
	test -x "$(VIRTUAL_ENV)/bin/sphinx-build" || ($(ACTIVATE) && pip-accel install --quiet sphinx)
	$(ACTIVATE) && cd docs && sphinx-build -b html -d build/doctrees . build/html

publish:
	git push origin && git push --tags origin
	make clean && python setup.py sdist upload

clean:
	rm -Rf .tox build dist docs/build *.egg-info *.egg htmlcov
	find -name __pycache__ -exec rm -R {} \; &>/dev/null || true
	find -type f -name '*.py[co]' -delete

.PHONY: default install reset test coverage check docs publish clean
