import Mathlib

-- Auto-generated verification file for HEAVEN
-- Statement: theorem

#check ∀ {K E : Type*} [Field K] [Field E] [Algebra K E] (p : K[X]),
  Polynomial.SolvableByRadicals p K E ↔ IsSolvable (GaloisGroup p K E)
