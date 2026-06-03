# Diagram Patterns

This document describes the common diagram types and when to use each one.
Each pattern includes a description, when to use it, and the recommended
element types and layout.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Module Dependency Graph](#module-dependency-graph)
3. [Class Hierarchy](#class-hierarchy)
4. [Data Flow Diagram](#data-flow-diagram)
5. [API Request Flow](#api-request-flow)
6. [ER Diagram](#er-diagram)
7. [Microservices Map](#microservices-map)
8. [Directory Structure Map](#directory-structure-map)

---

## Architecture Overview

**When to use**: High-level view of the entire system or a major subsystem.
Shows the main layers/components and their relationships.

**Elements**:
- Groups (swimlanes) for each architectural layer
- Rounded rectangles for components within each layer
- Cylinders for databases
- Hexagons for external systems

**Layout**: Layered (top-to-bottom), see Pattern 1 in layout-system.md

**Typical structure**:
```
Presentation Layer
  ├── Controllers / UI Components
  ├── Routes / Pages
Business Logic Layer
  ├── Services
  ├── Domain Models
Data Layer
  ├── Repositories
  ├── Database
External
  ├── Third-party APIs
  ├── Message Queues
```

**hedietLinkedDataV1 mapping**:
- Groups → directory paths (line numbers = "0")
- Components → file paths with full line ranges
- Databases → schema/migration files

---

## Module Dependency Graph

**When to use**: Show how modules/packages import and depend on each other.
Great for understanding coupling and identifying circular dependencies.

**Elements**:
- Rounded rectangles for each module/package
- Directed edges for import/dependency relationships
- Color-code by module type (service, util, model, etc.)

**Layout**: Hub-and-spoke or force-directed (center important modules)

**Edge labels**: Use the import type — "imports", "uses", "implements"

**hedietLinkedDataV1 mapping**:
- Modules → `index.ts` or main file of the module
- Edges → the specific import line in the source file

---

## Class Hierarchy

**When to use**: Show inheritance, composition, and implementation relationships
between classes. Useful for OOP-heavy codebases.

**Elements**:
- Rectangles with compartments for class name, attributes, methods
- Use UML-style notation

**Style for class boxes**:
```
shape=mxgraph.flowchart.annotation_1;whiteSpace=wrap;html=1;align=left;spacingLeft=10;fontSize=11
```

Or use the simpler approach with `label` containing HTML:
```
label="<b>ClassName</b><hr>attribute1: Type<br>attribute2: Type<hr>method1(): ReturnType<br>method2(): ReturnType"
```

With style:
```
rounded=0;whiteSpace=wrap;html=1;fillColor=#e6f7ff;strokeColor=#1890ff;verticalAlign=top;align=left;spacingLeft=10;spacingRight=10;overflow=fill;fontSize=11
```

**Layout**: Tree layout with base classes at top, subclasses below

**hedietLinkedDataV1 mapping**:
- Class box → the class definition line range
- Attributes → specific line numbers (if fine-grained linking desired)
- Methods → specific method line ranges

---

## Data Flow Diagram

**When to use**: Show how data moves through the system — from input to output,
through transformations, validations, and storage.

**Elements**:
- Parallelograms for inputs/outputs
- Rounded rectangles for processing steps
- Diamonds for decision points
- Cylinders for data stores

**Layout**: Left-to-right flow (see Pattern 3 in layout-system.md)

**Edge labels**: Name the data being passed — "UserDTO", "validated payload", "SQL query"

**hedietLinkedDataV1 mapping**:
- Processing steps → the function/method that performs the transformation
- Decision points → conditional logic (if/switch statements)
- Data stores → database schema or model files

---

## API Request Flow

**When to use**: Trace a single API request from entry to response. Shows
middleware chain, controller, service calls, and database queries.

**Elements**:
- Rounded rectangles for each handler in the chain
- Small circles for middleware checkpoints
- Cylinders for database interactions

**Layout**: Top-to-bottom sequential flow

**Example structure**:
```
Request → [Middleware: Auth] → [Middleware: Logger] → [Controller: handleGetUsers]
  → [Service: getUserList] → [Repository: findAll] → [Database]
  → Response
```

**hedietLinkedDataV1 mapping**:
- Each handler → the exact function that handles that step
- Middleware → the middleware function definition
- Edge labels → the data passed between steps

---

## ER Diagram

**When to use**: Show database entity relationships — tables, columns,
foreign keys, and cardinality.

**Elements**:
- Rectangles with compartments for entity name and columns
- Edges with cardinality notation

**Style for entity boxes** (using HTML label):
```
label="<b>TableName</b><hr>PK: id: integer<br>name: varchar(255)<br>FK: user_id: integer"
```

**Layout**: Grid layout with related entities near each other

**Edge cardinality notation**:
- One-to-one: `1 ── 1`
- One-to-many: `1 ── *`
- Many-to-many: `* ── *`

**hedietLinkedDataV1 mapping**:
- Entity → the model/schema definition file
- Columns → line numbers of specific column definitions
- Edges → the foreign key or relationship definition

---

## Microservices Map

**When to use**: Show the services in a microservices architecture, their
communication patterns, and shared infrastructure.

**Elements**:
- Rounded rectangles for each service
- Hexagons for shared infrastructure (API gateway, message bus, etc.)
- Cylinders for per-service databases
- Dashed edges for async communication
- Solid edges for sync communication

**Layout**: Hub-and-spoke with infrastructure in the center

**hedietLinkedDataV1 mapping**:
- Services → the service's main entry file
- Infrastructure → configuration files
- Communication edges → the client/producer code that makes the call

---

## Directory Structure Map

**When to use**: Quick overview of the project's file/folder organization.
Not a deep architecture diagram, but a navigable map.

**Elements**:
- Groups (swimlanes) for each top-level directory
- Small rounded rectangles for key files within each directory
- Tree-style indentation via positioning

**Layout**: Grid of groups, each containing a vertical list of files

**hedietLinkedDataV1 mapping**:
- Directory groups → the directory path (line numbers = "0")
- File elements → the file path (line numbers = "0" or "1" to "1" for the whole file)

---

## Choosing the Right Diagram

Ask yourself:

1. **What question is the user trying to answer?**
   - "How is this organized?" → Architecture Overview or Directory Structure Map
   - "What depends on what?" → Module Dependency Graph
   - "How does inheritance work?" → Class Hierarchy
   - "Where does data go?" → Data Flow Diagram
   - "How does this API work?" → API Request Flow
   - "What's the database schema?" → ER Diagram
   - "What services exist?" → Microservices Map

2. **How deep should we go?**
   - Start with a high-level overview (1-2 levels of detail)
   - Offer to drill down into specific modules on request
   - For large projects, generate multiple diagrams rather than one giant one

3. **What's the audience?**
   - For developers: include detailed hedietLinkedDataV1 links to exact lines
   - For stakeholders: use higher-level elements, fewer links, more descriptive labels
