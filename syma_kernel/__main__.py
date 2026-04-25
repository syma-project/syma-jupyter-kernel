"""Entry point for the Syma Jupyter kernel."""

from ipykernel.kernelapp import IPKernelApp
from .kernel import SymaKernel

IPKernelApp.launch_instance(kernel_class=SymaKernel)
