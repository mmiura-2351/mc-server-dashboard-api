# Java Version Compatibility Guide

## Overview

The Minecraft Server Dashboard API includes a comprehensive Java version compatibility system that automatically selects and validates the appropriate Java version for different Minecraft server versions. This ensures that servers can start successfully without Java-related compatibility issues.

## Supported Java Versions

The system supports multiple Java versions to accommodate different Minecraft server requirements:

- **Java 8**: Required for Minecraft 1.8 - 1.16.5
- **Java 16**: Required for Minecraft 1.17
- **Java 17**: Required for Minecraft 1.18 - 1.20.x
- **Java 21**: Required for Minecraft 1.21+

## Java Version Detection

The system automatically detects available Java installations using the following methods:

### 1. Environment Variable Configuration (Recommended)

Configure specific Java paths in your `.env` file:

```env
# Java Configuration
JAVA_8_PATH=/usr/lib/jvm/java-8-openjdk/bin/java
JAVA_16_PATH=/usr/lib/jvm/java-16-openjdk/bin/java
JAVA_17_PATH=/usr/lib/jvm/java-17-openjdk/bin/java
JAVA_21_PATH=/usr/lib/jvm/java-21-openjdk/bin/java

# Additional discovery paths (comma-separated)
JAVA_DISCOVERY_PATHS=/opt/java,/usr/local/java,/home/user/.sdkman/candidates/java
```

### 2. Automatic Discovery

If environment variables are not set, the system automatically searches for OpenJDK installations in common locations:

- `/usr/lib/jvm/`
- `/usr/local/jvm/`
- `/opt/java/`
- `/opt/openjdk/`
- System PATH

### 3. Supported Java Distributions

The system prioritizes OpenJDK distributions and recognizes:

- **Eclipse Temurin** (Adoptium)
- **AdoptOpenJDK**
- **Liberica JDK**
- **Azul Zulu**
- **Red Hat OpenJDK**
- Standard OpenJDK

## Configuration Examples

### Ubuntu/Debian Systems

```env
JAVA_8_PATH=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
JAVA_17_PATH=/usr/lib/jvm/java-17-openjdk-amd64/bin/java
JAVA_21_PATH=/usr/lib/jvm/java-21-openjdk-amd64/bin/java
```

### CentOS/RHEL Systems

```env
JAVA_8_PATH=/usr/lib/jvm/java-1.8.0-openjdk/bin/java
JAVA_17_PATH=/usr/lib/jvm/java-17-openjdk/bin/java
JAVA_21_PATH=/usr/lib/jvm/java-21-openjdk/bin/java
```

### SDKMAN! Managed Java

```env
JAVA_8_PATH=/home/user/.sdkman/candidates/java/8.0.412-tem/bin/java
JAVA_17_PATH=/home/user/.sdkman/candidates/java/17.0.11-tem/bin/java
JAVA_21_PATH=/home/user/.sdkman/candidates/java/21.0.3-tem/bin/java
JAVA_DISCOVERY_PATHS=/home/user/.sdkman/candidates/java
```

## Minecraft Version Compatibility Matrix

| Minecraft Version | Required Java | Notes |
|-------------------|---------------|-------|
| 1.8 - 1.16.5      | Java 8        | Legacy versions |
| 1.17              | Java 16       | First version requiring Java 16+ |
| 1.18 - 1.20.x     | Java 17       | LTS Java version recommended |
| 1.21+             | Java 21       | Latest versions require Java 21+ |

## Server Creation Process

When creating a new Minecraft server, the system:

1. **Validates Minecraft Version**: Checks if the requested Minecraft version is supported
2. **Determines Required Java**: Maps the Minecraft version to the required Java version
3. **Locates Java Installation**: Searches for a compatible Java installation
4. **Validates Compatibility**: Verifies the found Java version meets requirements
5. **Configures Server**: Uses the appropriate Java executable for server startup

## Error Handling

The system provides detailed error messages for common issues:

### No Java Found
```
No Java installations found. Please install OpenJDK and ensure it's accessible.
You can also configure specific Java paths in .env file.
```

### Incompatible Java Version
```
Minecraft 1.21.0 requires Java 21, but only Java [8, 17] are available.
Please install Java 21 or configure JAVA_21_PATH in .env.
```

### Java Detection Failure
```
Java compatibility check failed: Unable to detect Java version at /path/to/java
```

## Installation Recommendations

### Installing Multiple Java Versions

#### Ubuntu/Debian
```bash
# Install multiple OpenJDK versions
sudo apt update
sudo apt install openjdk-8-jdk openjdk-17-jdk openjdk-21-jdk

# List installed versions
sudo update-alternatives --list java
```

#### CentOS/RHEL
```bash
# Install multiple OpenJDK versions
sudo dnf install java-1.8.0-openjdk java-17-openjdk java-21-openjdk

# List installed versions
alternatives --list | grep java
```

#### Using SDKMAN!
```bash
# Install SDKMAN!
curl -s "https://get.sdkman.io" | bash
source "$HOME/.sdkman/bin/sdkman-init.sh"

# Install multiple Java versions
sdk install java 8.0.412-tem
sdk install java 17.0.11-tem
sdk install java 21.0.3-tem

# List installed versions
sdk list java
```

## Troubleshooting

### Common Issues

1. **Java Not Found**: Ensure Java is installed and paths are correct
2. **Permission Issues**: Verify Java executables have proper permissions
3. **Path Resolution**: Use absolute paths in environment variables
4. **Version Detection**: Check Java version output format compatibility

### Debugging Commands

```bash
# Check Java installations
ls -la /usr/lib/jvm/

# Test Java version detection
/usr/lib/jvm/java-17-openjdk/bin/java -version

# Verify environment variables
echo $JAVA_17_PATH
```

### Log Analysis

The system logs detailed information about Java detection:

```log
INFO: Selected Java 17 (17.0.11+9) at /usr/lib/jvm/java-17-openjdk/bin/java [Eclipse Temurin]
INFO: Java compatibility verified for Minecraft 1.20.1: Compatible with Java 17
```

## API Integration

The Java compatibility system integrates seamlessly with the server management API:

- **Server Creation**: Automatic Java validation during server creation
- **Server Startup**: Runtime Java compatibility checking
- **Error Reporting**: Detailed compatibility error messages in API responses
- **Configuration Validation**: Pre-flight checks before resource allocation

## Best Practices

1. **Use Environment Variables**: Configure specific Java paths for reliable detection
2. **Install LTS Versions**: Prioritize Java 8, 17, and 21 for broad compatibility
3. **Test Installations**: Verify Java installations work correctly before server creation
4. **Monitor Logs**: Check application logs for Java detection issues
5. **Keep Updated**: Regularly update Java installations for security and compatibility

## Performance Considerations

- Java detection is cached for performance
- Version validation occurs only during server creation and startup
- Automatic discovery has minimal overhead with configured paths
- Failed detections are logged but don't block other operations

## Future Compatibility

The system is designed to accommodate future Minecraft and Java versions:

- Easy addition of new Java version mappings
- Extensible Java detection mechanisms
- Configurable compatibility rules
- Forward-compatible error handling

## Related Documentation

- [Server Management API](api-reference.md#servers)
- [Configuration Guide](development.md#configuration)
- [Architecture Overview](architecture.md)
- [Troubleshooting Guide](development.md#troubleshooting)
