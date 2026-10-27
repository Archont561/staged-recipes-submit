Feature: Submitting conda recipes to conda-forge/staged-recipes
  Recipes are validated locally and a pull request is opened only when the plan
  is clean. Nothing is merged and nothing is published.

  Scenario: A valid recipe is submitted through one pull request
    Given a fork "archont561/staged-recipes"
    And a valid recipe "hello-world" version "0.1.0"
    When I submit the recipe
    Then one pull request is created
    And the branch is "submit/hello-world"
    And the recipe lands in "recipes/hello-world"

  Scenario: Several recipes are submitted in one invocation
    Given a fork "archont561/staged-recipes"
    And a valid recipe "alpha" version "1.0.0"
    And a valid recipe "beta" version "2.0.0"
    When I submit the recipe
    Then one pull request is created
    And the pull request mentions "alpha" and "beta"

  Scenario: An invalid recipe is rejected before any remote change
    Given a fork "archont561/staged-recipes"
    And a recipe "broken" without a package section
    When I submit the recipe
    Then the submission fails with code "VAL003"
    And no pull request is created
    And no branch is pushed

  Scenario: A duplicate package is rejected with an actionable hint
    Given a fork "archont561/staged-recipes"
    And a valid recipe "numpy" version "2.0.0"
    And the upstream already has a recipe for "numpy"
    When I submit the recipe
    Then the submission fails with code "DUP002"
    And the hint explains the next step
    And no pull request is created

  Scenario: A rerun reuses the existing branch and pull request
    Given a fork "archont561/staged-recipes"
    And a valid recipe "hello-world" version "0.1.0"
    When I submit the recipe
    And I submit the recipe again
    Then one pull request is created
    And the second run reuses it

  Scenario: A dry run performs no remote writes
    Given a fork "archont561/staged-recipes"
    And a valid recipe "hello-world" version "0.1.0"
    When I submit the recipe as a dry run
    Then the report is a dry run
    And no pull request is created
    And no branch is pushed
