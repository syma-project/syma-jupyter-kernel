"""Packaging for the Syma Jupyter kernel."""

from setuptools import setup, find_packages

setup(
    name="syma-kernel",
    version="0.1.0",
    description="Jupyter kernel for the Syma symbolic-first programming language",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/syma-project/syma",
    author="Syma Contributors",
    license="MIT",
    packages=find_packages(),
    install_requires=[
        "ipykernel>=6.0",
        "jupyter_client>=7.0",
    ],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Framework :: Jupyter",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Rust",
        "Topic :: Scientific/Engineering",
        "Topic :: Software Development :: Interpreters",
    ],
    python_requires=">=3.8",
)
