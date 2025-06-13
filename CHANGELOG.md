# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Java Version Compatibility Management** - Comprehensive multi-version Java support for Minecraft servers
  - Automatic Java version detection and selection based on Minecraft version requirements
  - Support for Java 8, 16, 17, and 21 with configurable paths via environment variables
  - OpenJDK discovery in common installation paths with vendor detection
  - Detailed error messages for Java compatibility issues
  - Java compatibility validation during server creation and startup
  - Environment variable configuration: `JAVA_8_PATH`, `JAVA_16_PATH`, `JAVA_17_PATH`, `JAVA_21_PATH`
  - Custom discovery paths via `JAVA_DISCOVERY_PATHS` environment variable
  - Comprehensive documentation in [Java Compatibility Guide](docs/java-compatibility.md)

### Changed
- Enhanced server creation process with pre-flight Java compatibility checks
- Improved error handling for Java-related server startup failures
- Updated MinecraftServerManager to use version-specific Java executables

### Fixed
- Resolved Issue #29: Java Version Compatibility Management for Multi-Version Minecraft Servers
- Fixed test failures in `test_minecraft_server_enhanced_coverage.py` and `test_minecraft_server_key_methods.py`
- Updated test methods to match new Java compatibility API signature

### Documentation
- Added comprehensive [Java Compatibility Guide](docs/java-compatibility.md)
- Updated README.md with Java configuration examples
- Enhanced API reference with Java compatibility information
- Updated architecture documentation to include JavaCompatibilityService

## Previous Versions

Previous changes are tracked in git commit history. This changelog was started with the Java compatibility feature implementation.