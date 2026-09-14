"""
Setup script for the `yieldfabric-cli` distribution.

One import package (`yieldfabric`) ships two console scripts:

  yf          — the command-line client (yieldfabric.yf.main)
  yieldfabric — the YAML command-file runner / setup harness (yieldfabric.cli)
"""

from setuptools import setup, find_packages
import os

def read_readme():
    readme_path = os.path.join(os.path.dirname(__file__), 'README.md')
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            return f.read()
    return "YieldFabric command-line client (`yf`) and YAML command runner (`yieldfabric`)"

def read_requirements():
    requirements_path = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    if os.path.exists(requirements_path):
        with open(requirements_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    return [
        'requests>=2.31.0',
        'PyYAML>=6.0.1'
    ]

setup(
    # Distribution name (what `pip install` takes). The import package
    # stays `yieldfabric`. `yf` / `yf-cli` are unrelated PyPI projects, so
    # the distribution is namespaced; the console script is still `yf`.
    name="yieldfabric-cli",
    version="2.1.0",
    author="YieldFabric Team",
    author_email="team@yieldfabric.io",
    description="YieldFabric command-line client (yf) and YAML command runner",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    url="https://github.com/yieldfabric/yieldfabric-docs",
    packages=find_packages(include=['yieldfabric', 'yieldfabric.*']),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.8",
    install_requires=read_requirements(),
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "pytest-cov>=4.1.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.5.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "yf=yieldfabric.yf.main:main",
            "yieldfabric=yieldfabric.cli:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
    keywords="yieldfabric, cli, graphql, yaml, commands, payments, obligations",
    project_urls={
        "Bug Reports": "https://github.com/yieldfabric/yieldfabric-docs/issues",
        "Source": "https://github.com/yieldfabric/yieldfabric-docs",
    },
)

