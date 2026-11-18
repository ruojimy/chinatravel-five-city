"""Atomic entrypoint for source-validated rail evidence materialization."""
from materialize_live_impl import *
import materialize_live_impl as impl
from atomic_materialize import atomic_main

if __name__=='__main__':atomic_main(impl.main)
