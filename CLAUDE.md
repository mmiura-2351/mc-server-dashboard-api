# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this documentation repository.

## Documentation Project Rules

### Rule 1: Documentation Quality Standards
**Maintain consistent high-quality documentation across all documents.**

When creating or updating documentation:
1. **Accuracy**: Ensure all technical specifications are accurate and implementable
2. **Completeness**: Cover all aspects of the specified topic comprehensively
3. **Consistency**: Use consistent terminology, formatting, and structure across documents
4. **Bilingual Support**: Maintain both English and Japanese versions with equal quality

### Rule 2: Document Structure Standards
**Follow consistent document structure and formatting.**

All technical documents should include:
1. **Clear Overview**: Executive summary of the document's purpose and scope
2. **Structured Sections**: Logical organization with clear headings and subheadings
3. **Code Examples**: Practical implementation examples where applicable
4. **Cross-References**: Links to related documents and sections
5. **Version Control**: Track document versions and update history

### Rule 3: Technical Specification Accuracy
**Ensure all technical specifications are implementable and realistic.**

When creating technical specifications:
1. **Feasibility Review**: Verify all proposed solutions are technically feasible
2. **Performance Targets**: Set realistic performance benchmarks based on technology capabilities
3. **Security Requirements**: Include comprehensive security considerations
4. **Integration Points**: Clearly define how components interact with each other

### Rule 4: Architecture Documentation Standards
**Document architecture decisions with clear rationale and trade-offs.**

Architecture documentation should include:
1. **Decision Rationale**: Explain why specific architectural choices were made
2. **Trade-off Analysis**: Document alternatives considered and reasons for rejection
3. **Future Considerations**: Address scalability and evolution paths
4. **Implementation Guidelines**: Provide clear guidance for developers

### Rule 5: Japanese Translation Quality
**Maintain professional-grade Japanese translations with technical accuracy.**

When creating Japanese translations:
1. **Technical Terminology**: Use appropriate Japanese technical terms consistently
2. **Cultural Adaptation**: Adapt content structure for Japanese business communication style
3. **Accuracy Verification**: Ensure technical accuracy is maintained in translation
4. **Consistency**: Maintain consistent translation of key terms across documents

## Project Overview

This branch contains comprehensive documentation for the Minecraft Server Dashboard API V2 project rebuild. The documentation suite provides complete specifications for rebuilding the existing V1 system from the ground up to address architectural complexity and technical debt.

## Documentation Structure

### Core Documentation Files

| Document | Description | Languages |
|----------|-------------|-----------|
| `new-architecture-design.md` | Complete V2 architecture design with Domain-Driven Design | EN, JA |
| `technical-specification.md` | Detailed implementation patterns and code examples | EN, JA |
| `database-design.md` | Complete PostgreSQL schema design with optimization | EN, JA |
| `api-design.md` | RESTful API specification with 100+ endpoints | EN, JA |
| `security-performance-requirements.md` | Enterprise security and performance targets | EN, JA |
| `development-roadmap.md` | 14-week phased development plan | EN, JA |
| `project-rebuild-summary.md` | Executive summary and ROI analysis | EN |

### Architecture Overview

The V2 rebuild addresses current system complexity through:

**Domain-Driven Design**: 7 clean bounded contexts replacing 19 tightly coupled services
- `users/` - User Management Context
- `servers/` - Server Management Context  
- `groups/` - Group Management Context
- `backups/` - Backup Management Context
- `templates/` - Template Management Context
- `files/` - File Management Context
- `monitoring/` - Monitoring Context

**CQRS + Event Sourcing**: Separate read/write models with event-driven architecture
- Command handlers for write operations
- Query handlers for read operations
- Event-driven inter-service communication

**Technology Stack Modernization**:
- FastAPI with improved patterns
- PostgreSQL 15+ with performance optimization
- Redis 7+ for caching and job queues
- Comprehensive monitoring and observability

## Feature Parity

The rebuild maintains 100% feature parity across all 46 use cases (UC1-46):
- User Management (UC38-42)
- Server Management (UC1-11)
- Group Management (UC12-19)
- Backup Management (UC21-28)
- Template Management (UC29-32)
- File Management (UC33-37)
- Real-time Features (UC20)
- Administrative Functions (UC43-46)

## Implementation Timeline

**Total Duration**: 14 weeks (5 phases, 10 sprints)
1. **Foundation** (Weeks 1-2): Authentication and core infrastructure
2. **Core Domains** (Weeks 3-6): Server, group, and backup management
3. **Advanced Features** (Weeks 7-10): Templates, files, and background processing
4. **Real-time & Monitoring** (Weeks 11-12): WebSocket features and observability
5. **Migration & Deployment** (Weeks 13-14): Data migration and production rollout

## Expected Benefits

- **70% reduction** in maintenance overhead
- **3x faster** new feature development
- **Enterprise-grade security** with comprehensive audit
- **10x scalability** with same infrastructure
- **<200ms API response** times (95th percentile)
- **1000+ concurrent users** supported