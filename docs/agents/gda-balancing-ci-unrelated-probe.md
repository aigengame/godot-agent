# Disposable gda-balancing CI probe

This branch-only file verifies that an explicitly unrelated root documentation
change receives a successful `gda-balancing required` result without starting
the balancing test matrix. The probe PR must be closed without merging after
the timing evidence is recorded on issue #597.
