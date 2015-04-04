# Makefile for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: January 14, 2015
# URL: https://github.com/paylogic/pip-accel

WORKON_HOME ?= $(HOME)/.virtualenvs
VIRTUAL_ENV ?= $(WORKON_HOME)/pip-accel
ACTIVATE = . "$(VIRTUAL_ENV)/bin/activate"

default:
	@echo 'Makefile for the pip accelerator'
	@echo
	@echo 'Usage:'
	@echo
	@echo '    make install    install the package in a virtual environment'
	@echo '    make reset      recreate the virtual environment'
	@echo '    make test       run the unit test suite'
	@echo '    make coverage   run the tests, report coverage'
	@echo '    make docs       update documentation using Sphinx'
	@echo '    make publish    publish changes to GitHub/PyPI'
	@echo '    make clean      cleanup all temporary files'
	@echo

install:
	test -d "$(VIRTUAL_ENV)" || virtualenv "$(VIRTUAL_ENV)"
	test -x "$(VIRTUAL_ENV)/bin/pip" || ($(ACTIVATE) && easy_install pip)
	$(ACTIVATE) && pip uninstall -y pip-accel || true
	$(ACTIVATE) && pip install --editable .

reset:
	rm -Rf "$(VIRTUAL_ENV)"
	make --no-print-directory clean install

test: install
	pip-accel install -r requirements-testing.txt
	tox

coverage: install
	test -x "$(VIRTUAL_ENV)/bin/coverage" || ($(ACTIVATE) && pip-accel install coverage)
	$(ACTIVATE) && coverage run --source=pip_accel setup.py test
	$(ACTIVATE) && coverage html --omit=pip_accel/tests.py

docs: install
	test -x "$(VIRTUAL_ENV)/bin/sphinx-build" || ($(ACTIVATE) && pip-accel install sphinx)
	$(ACTIVATE) && cd docs && sphinx-build -b html -d build/doctrees . build/html

publish:
	git push origin && git push --tags origin
	make clean && python setup.py sdist upload

clean:
	rm -Rf .tox build dist docs/build *.egg-info *.egg
	find -name __pycache__ -exec rm -R {} \; 2>/dev/null || true

.PHONY: default install reset test coverage docs publish clean
