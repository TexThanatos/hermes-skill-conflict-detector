from setuptools import setup, find_packages

setup(
    name="hermes-skill-conflict-detector",
    version="0.1.0",
    description="Detect conflicts and relationship issues between Hermes Agent skills",
    author="TexThanatos",
    author_email="2915674986@qq.com",
    url="https://github.com/TexThanatos/hermes-skill-conflict-detector",
    packages=find_packages(),
    install_requires=[
        "pyyaml>=6.0",
    ],
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "skill-conflicts=skill_conflict_detector.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Software Development :: Quality Assurance",
    ],
)
