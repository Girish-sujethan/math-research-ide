import Lake
open Lake DSL

package «heaven» where

-- Mathlib4: the community library of formalized mathematics (~150k theorems)
-- This is what HEAVEN checks discoveries against
require mathlib from git
  "https://github.com/leanprover-community/mathlib4" @ "master"

lean_lib «HEAVEN» where
  -- Source files live in server/lean_project/HEAVEN/
