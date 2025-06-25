# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **Version Management Timeout Issues** - Simplified timeout handling and improved API reliability
  - Identified root cause: systemd service IPAddressAllow restrictions blocking external API calls
  - Removed unnecessary complex timeout logic (31.7 minute timeouts reduced to 60 seconds)
  - Improved HTTP client configuration with proper connect/read timeouts
  - Added User-Agent and Accept-Encoding headers for better API compatibility
  - Simplified error handling while maintaining functionality
  - Removed ~780 lines of unnecessary timeout handling code
  - Fixed gzip decoding issues with Forge Maven API
  - All version manager unit tests now pass (31/31)

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
- Simplified version management system architecture by removing unnecessary complexity

### Documentation
- Added comprehensive [Java Compatibility Guide](docs/java-compatibility.md)
- Updated README.md with Java configuration examples
- Enhanced API reference with Java compatibility information
- Updated architecture documentation to include JavaCompatibilityService

## Previous Versions

Previous changes are tracked in git commit history. This changelog was started with the Java compatibility feature implementation.
