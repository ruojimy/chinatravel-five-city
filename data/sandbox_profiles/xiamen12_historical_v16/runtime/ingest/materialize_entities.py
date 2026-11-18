"""Atomic entrypoint for source-validated entity evidence materialization."""
from materialize_entities_impl import *
import materialize_entities_impl as impl
from atomic_materialize import atomic_main

if __name__=='__main__':atomic_main(impl.main)
