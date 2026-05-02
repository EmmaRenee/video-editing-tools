"""
Setup script for videoedit package.

Installation:
    pip install -e .
"""
from pathlib import Path
from setuptools import setup, find_packages

README = (Path(__file__).parent / "README.md").read_text()

setup(
    name="videoedit",
    version="0.2.0",
    description="AI-first video editing pipeline system",
    long_description=README,
    long_description_content_type="text/markdown",
    url="https://github.com/EmmaRenee/video-editing-tools",
    author="Emma Werner",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "click>=8.0.0",
        "pyyaml>=6.0",
        "textual>=0.50.0",
        "rich>=13.0.0",
    ],
    extras_require={
        "whisper": ["openai-whisper>=20231117"],
        "cloud": ["elevenlabs", "python-dotenv"],
    },
    entry_points={
        "console_scripts": [
            "videoedit=videoedit.cli:main",
        ],
    },
    python_requires=">=3.9",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
