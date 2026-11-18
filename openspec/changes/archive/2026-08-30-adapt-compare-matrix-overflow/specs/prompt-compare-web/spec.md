# prompt-compare-web Delta — adapt-compare-matrix-overflow

## ADDED Requirements

### Requirement: Matrix Horizontal Overflow Behavior
The verdict matrix SHALL remain fully readable when its columns exceed the panel width: the matrix SHALL scroll horizontally within a container inside its panel rather than overflowing or clipping, the table SHALL carry a minimum width so narrow results do not collapse columns illegibly, and the header's raw prompt-name subline SHALL be allowed to wrap while the localized display title and verdict cells keep single-line rendering. No content SHALL be clipped without a scroll path to it.

#### Scenario: many columns scroll instead of breaking layout
- **WHEN** a compare result renders with enough prompts that the matrix exceeds the 980px panel width
- **THEN** the matrix scrolls horizontally inside its container and the page layout does not break

#### Scenario: narrow matrices stay legible
- **WHEN** a compare result has few prompts
- **THEN** the table retains a minimum width that keeps criterion labels and verdict cells legible

#### Scenario: long prompt names wrap in the header subline
- **WHEN** a column header's raw prompt name is longer than its column
- **THEN** the muted prompt-name subline wraps while the localized display title above it stays on one line
