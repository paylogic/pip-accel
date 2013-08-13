# Makefile for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: August 14, 2013
# URL: https://github.com/paylogic/pip-accel

default:
	@echo 'Makefile for the pip accelerator'
	@echo
	@echo 'Usage:'
	@echo
	@echo '    make test       run the unit test suite'
	@echo '    make docs       update documentation using Sphinx'
	@echo '    make publish    publish changes to GitHub/PyPI'
	@echo '    make clean      cleanup all temporary files'
	@echo

test:
	python setup.py test

clean:
	rm -Rf .tox build dist docs/build *.egg-info *.egg
	find -name __pycache__ -exec rm -R {} \; 2>/dev/null || true

docs:
	cd docs && make html

publish:
	git push origin && git push --tags origin
	make clean && python setup.py sdist upload

.PHONY: docs
