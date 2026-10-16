from setuptools import find_packages, setup


setup(
    name="ai-co-scientist-demo",
    version="0.1.0",
    description="A sanitized, evidence-gated multi-agent research workflow demo",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=["pydantic>=2.8,<3"],
    extras_require={"live": ["openai>=1.40,<3"]},
)
