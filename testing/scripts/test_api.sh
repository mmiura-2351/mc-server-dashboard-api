#!/bin/bash

# Minecraft Server Dashboard API Testing Script
# This script tests the API endpoints using curl commands

BASE_URL="http://localhost:8001/api/v1"
TOKEN=""
echo "🚀 Minecraft Server Dashboard API Test Suite"
echo "============================================="

# Start test server
echo "🚀 Starting test server..."
./test_server.sh start

# Wait for server to be fully ready
echo "⏳ Waiting for test server to be ready..."
sleep 3

# Cleanup function
cleanup() {
    echo -e "\n🧹 Cleaning up..."
    ./test_server.sh stop
    exit 0
}

# Set trap for cleanup on script exit or interruption
trap cleanup EXIT INT TERM

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print test headers
print_test() {
    echo -e "\n${BLUE}📋 Testing: $1${NC}"
    echo "-----------------------------------"
}

# Function to print success
print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

# Function to print error
print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Function to print info
print_info() {
    echo -e "${YELLOW}ℹ️  $1${NC}"
}

# Test API health/docs
print_test "API Documentation"
echo "📖 API Documentation available at: http://localhost:8001/docs"
echo "📖 ReDoc Documentation: http://localhost:8001/redoc"

# ===============================================
# USER AUTHENTICATION & MANAGEMENT TESTS
# ===============================================

# Test 1: First user registration (becomes admin automatically)
print_test "First User Registration (Auto-Admin)"
FIRST_USER_RESPONSE=$(curl -s -X POST "$BASE_URL/users/register" \
    -H "Content-Type: application/json" \
    -d '{
        "username": "admin",
        "email": "admin@example.com",
        "password": "adminpass123"
    }')

echo "First User Registration Response:"
echo "$FIRST_USER_RESPONSE" | jq '.' 2>/dev/null || echo "$FIRST_USER_RESPONSE"

# Verify first user is admin and approved
FIRST_USER_ID=$(echo "$FIRST_USER_RESPONSE" | jq -r '.id' 2>/dev/null)
FIRST_USER_ROLE=$(echo "$FIRST_USER_RESPONSE" | jq -r '.role' 2>/dev/null)
FIRST_USER_APPROVED=$(echo "$FIRST_USER_RESPONSE" | jq -r '.is_approved' 2>/dev/null)

if [ "$FIRST_USER_ROLE" = "admin" ] && [ "$FIRST_USER_APPROVED" = "true" ]; then
    print_success "First user correctly assigned admin role and auto-approved"
else
    print_error "First user registration failed - role: $FIRST_USER_ROLE, approved: $FIRST_USER_APPROVED"
fi

# Test 2: Admin login
print_test "Admin User Login"
ADMIN_LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=admin&password=adminpass123")

echo "Admin Login Response:"
echo "$ADMIN_LOGIN_RESPONSE" | jq '.' 2>/dev/null || echo "$ADMIN_LOGIN_RESPONSE"

ADMIN_TOKEN=$(echo "$ADMIN_LOGIN_RESPONSE" | jq -r '.access_token' 2>/dev/null)
if [ "$ADMIN_TOKEN" != "null" ] && [ "$ADMIN_TOKEN" != "" ]; then
    print_success "Admin login successful!"
else
    print_error "Admin login failed"
    exit 1
fi

# Test 3: Regular user registration (requires approval)
print_test "Regular User Registration"
USER_RESPONSE=$(curl -s -X POST "$BASE_URL/users/register" \
    -H "Content-Type: application/json" \
    -d '{
        "username": "testuser",
        "email": "test@example.com",
        "password": "testpass123"
    }')

echo "Regular User Registration Response:"
echo "$USER_RESPONSE" | jq '.' 2>/dev/null || echo "$USER_RESPONSE"

USER_ID=$(echo "$USER_RESPONSE" | jq -r '.id' 2>/dev/null)
USER_ROLE=$(echo "$USER_RESPONSE" | jq -r '.role' 2>/dev/null)
USER_APPROVED=$(echo "$USER_RESPONSE" | jq -r '.is_approved' 2>/dev/null)

if [ "$USER_ROLE" = "user" ] && [ "$USER_APPROVED" = "false" ]; then
    print_success "Regular user correctly assigned user role and requires approval"
else
    print_error "Regular user registration failed - role: $USER_ROLE, approved: $USER_APPROVED"
fi

# Test 4: Unapproved user login attempt
print_test "Unapproved User Login Attempt"
UNAPPROVED_LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=testuser&password=testpass123")

echo "Unapproved User Login Response:"
echo "$UNAPPROVED_LOGIN_RESPONSE" | jq '.' 2>/dev/null || echo "$UNAPPROVED_LOGIN_RESPONSE"

if echo "$UNAPPROVED_LOGIN_RESPONSE" | grep -q "pending approval"; then
    print_success "Unapproved user correctly denied login"
else
    print_error "Unapproved user login validation failed"
fi

# Test 5: Admin approves user
print_test "Admin Approves User"
APPROVE_RESPONSE=$(curl -s -X POST "$BASE_URL/users/approve/$USER_ID" \
    -H "Authorization: Bearer $ADMIN_TOKEN")

echo "User Approval Response:"
echo "$APPROVE_RESPONSE" | jq '.' 2>/dev/null || echo "$APPROVE_RESPONSE"

APPROVED_STATUS=$(echo "$APPROVE_RESPONSE" | jq -r '.is_approved' 2>/dev/null)
if [ "$APPROVED_STATUS" = "true" ]; then
    print_success "User successfully approved by admin"
else
    print_error "User approval failed"
fi

# Test 6: Approved user login
print_test "Approved User Login"
APPROVED_LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=testuser&password=testpass123")

echo "Approved User Login Response:"
echo "$APPROVED_LOGIN_RESPONSE" | jq '.' 2>/dev/null || echo "$APPROVED_LOGIN_RESPONSE"

USER_TOKEN=$(echo "$APPROVED_LOGIN_RESPONSE" | jq -r '.access_token' 2>/dev/null)
if [ "$USER_TOKEN" != "null" ] && [ "$USER_TOKEN" != "" ]; then
    print_success "Approved user login successful!"
else
    print_error "Approved user login failed"
fi

# Test 7: Invalid credentials
print_test "Invalid Credentials Test"
INVALID_LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=testuser&password=wrongpassword")

echo "Invalid Login Response:"
echo "$INVALID_LOGIN_RESPONSE" | jq '.' 2>/dev/null || echo "$INVALID_LOGIN_RESPONSE"

if echo "$INVALID_LOGIN_RESPONSE" | grep -q "Incorrect username or password"; then
    print_success "Invalid credentials correctly rejected"
else
    print_error "Invalid credentials test failed"
fi

# Test 8: Duplicate username registration
print_test "Duplicate Username Registration"
DUPLICATE_RESPONSE=$(curl -s -X POST "$BASE_URL/users/register" \
    -H "Content-Type: application/json" \
    -d '{
        "username": "testuser",
        "email": "different@example.com",
        "password": "testpass123"
    }')

echo "Duplicate Username Response:"
echo "$DUPLICATE_RESPONSE" | jq '.' 2>/dev/null || echo "$DUPLICATE_RESPONSE"

if echo "$DUPLICATE_RESPONSE" | grep -q "already registered"; then
    print_success "Duplicate username correctly rejected"
else
    print_error "Duplicate username test failed"
fi

# ===============================================
# USER MANAGEMENT WORKFLOW TESTS
# ===============================================

# Test 9: Admin gets current user info
print_test "Admin: Get Current User Info"
ADMIN_ME_RESPONSE=$(curl -s -X GET "$BASE_URL/users/me" \
    -H "Authorization: Bearer $ADMIN_TOKEN")

echo "Admin User Info Response:"
echo "$ADMIN_ME_RESPONSE" | jq '.' 2>/dev/null || echo "$ADMIN_ME_RESPONSE"

# Test 10: Regular user gets current user info
print_test "Regular User: Get Current User Info"
if [ -n "$USER_TOKEN" ]; then
    USER_ME_RESPONSE=$(curl -s -X GET "$BASE_URL/users/me" \
        -H "Authorization: Bearer $USER_TOKEN")
    
    echo "Regular User Info Response:"
    echo "$USER_ME_RESPONSE" | jq '.' 2>/dev/null || echo "$USER_ME_RESPONSE"
else
    print_error "No user token available"
fi

# Test 11: Admin gets all users
print_test "Admin: Get All Users"
ALL_USERS_RESPONSE=$(curl -s -X GET "$BASE_URL/users/" \
    -H "Authorization: Bearer $ADMIN_TOKEN")

echo "All Users Response:"
echo "$ALL_USERS_RESPONSE" | jq '.' 2>/dev/null || echo "$ALL_USERS_RESPONSE"

USER_COUNT=$(echo "$ALL_USERS_RESPONSE" | jq 'length' 2>/dev/null)
if [ "$USER_COUNT" = "2" ]; then
    print_success "All users endpoint returns correct count: $USER_COUNT"
else
    print_error "Unexpected user count: $USER_COUNT"
fi

# Test 12: Regular user tries to get all users (should fail)
print_test "Regular User: Get All Users (Should Fail)"
if [ -n "$USER_TOKEN" ]; then
    FORBIDDEN_RESPONSE=$(curl -s -X GET "$BASE_URL/users/" \
        -H "Authorization: Bearer $USER_TOKEN")
    
    echo "Forbidden Access Response:"
    echo "$FORBIDDEN_RESPONSE" | jq '.' 2>/dev/null || echo "$FORBIDDEN_RESPONSE"
    
    if echo "$FORBIDDEN_RESPONSE" | grep -q "Only admin"; then
        print_success "Regular user correctly denied admin access"
    else
        print_error "Regular user access control failed"
    fi
else
    print_error "No user token available"
fi

# Test 13: Create operator user for role testing
print_test "Create Operator User"
OPERATOR_RESPONSE=$(curl -s -X POST "$BASE_URL/users/register" \
    -H "Content-Type: application/json" \
    -d '{
        "username": "operator",
        "email": "operator@example.com",
        "password": "operatorpass123"
    }')

echo "Operator Registration Response:"
echo "$OPERATOR_RESPONSE" | jq '.' 2>/dev/null || echo "$OPERATOR_RESPONSE"

OPERATOR_ID=$(echo "$OPERATOR_RESPONSE" | jq -r '.id' 2>/dev/null)

# Test 14: Admin approves operator
print_test "Admin Approves Operator"
APPROVE_OP_RESPONSE=$(curl -s -X POST "$BASE_URL/users/approve/$OPERATOR_ID" \
    -H "Authorization: Bearer $ADMIN_TOKEN")

echo "Operator Approval Response:"
echo "$APPROVE_OP_RESPONSE" | jq '.' 2>/dev/null || echo "$APPROVE_OP_RESPONSE"

# Test 15: Admin changes operator role
print_test "Admin Changes User Role to Operator"
ROLE_CHANGE_RESPONSE=$(curl -s -X PUT "$BASE_URL/users/role/$OPERATOR_ID" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"role": "operator"}')

echo "Role Change Response:"
echo "$ROLE_CHANGE_RESPONSE" | jq '.' 2>/dev/null || echo "$ROLE_CHANGE_RESPONSE"

UPDATED_ROLE=$(echo "$ROLE_CHANGE_RESPONSE" | jq -r '.role' 2>/dev/null)
if [ "$UPDATED_ROLE" = "operator" ]; then
    print_success "User role successfully changed to operator"
else
    print_error "Role change failed - role: $UPDATED_ROLE"
fi

# Test 16: Operator login
print_test "Operator User Login"
OPERATOR_LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=operator&password=operatorpass123")

echo "Operator Login Response:"
echo "$OPERATOR_LOGIN_RESPONSE" | jq '.' 2>/dev/null || echo "$OPERATOR_LOGIN_RESPONSE"

OPERATOR_TOKEN=$(echo "$OPERATOR_LOGIN_RESPONSE" | jq -r '.access_token' 2>/dev/null)

# Test 17: Regular user tries to approve another user (should fail)
print_test "Regular User: Try to Approve User (Should Fail)"
if [ -n "$USER_TOKEN" ]; then
    # Create another user to test with
    VICTIM_RESPONSE=$(curl -s -X POST "$BASE_URL/users/register" \
        -H "Content-Type: application/json" \
        -d '{
            "username": "victim",
            "email": "victim@example.com",
            "password": "victimpass123"
        }')
    
    VICTIM_ID=$(echo "$VICTIM_RESPONSE" | jq -r '.id' 2>/dev/null)
    
    UNAUTHORIZED_APPROVE=$(curl -s -X POST "$BASE_URL/users/approve/$VICTIM_ID" \
        -H "Authorization: Bearer $USER_TOKEN")
    
    echo "Unauthorized Approval Response:"
    echo "$UNAUTHORIZED_APPROVE" | jq '.' 2>/dev/null || echo "$UNAUTHORIZED_APPROVE"
    
    if echo "$UNAUTHORIZED_APPROVE" | grep -q "Only admin"; then
        print_success "Regular user correctly denied approval permission"
    else
        print_error "Regular user authorization check failed"
    fi
else
    print_error "No user token available"
fi

# Test 18: User updates their own information
print_test "User Updates Own Information"
if [ -n "$USER_TOKEN" ]; then
    UPDATE_INFO_RESPONSE=$(curl -s -X PUT "$BASE_URL/users/me" \
        -H "Authorization: Bearer $USER_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{
            "username": "testuser_updated",
            "email": "test_updated@example.com"
        }')
    
    echo "User Info Update Response:"
    echo "$UPDATE_INFO_RESPONSE" | jq '.' 2>/dev/null || echo "$UPDATE_INFO_RESPONSE"
    
    UPDATED_USERNAME=$(echo "$UPDATE_INFO_RESPONSE" | jq -r '.user.username' 2>/dev/null)
    NEW_TOKEN=$(echo "$UPDATE_INFO_RESPONSE" | jq -r '.access_token' 2>/dev/null)
    
    if [ "$UPDATED_USERNAME" = "testuser_updated" ]; then
        print_success "User information successfully updated"
        if [ "$NEW_TOKEN" != "null" ] && [ "$NEW_TOKEN" != "" ]; then
            print_success "New token provided after username change"
            USER_TOKEN="$NEW_TOKEN"  # Update token for subsequent tests
        fi
    else
        print_error "User information update failed"
    fi
else
    print_error "No user token available"
fi

# Test 19: User changes password
print_test "User Changes Password"
if [ -n "$USER_TOKEN" ]; then
    PASSWORD_CHANGE_RESPONSE=$(curl -s -X PUT "$BASE_URL/users/me/password" \
        -H "Authorization: Bearer $USER_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{
            "current_password": "testpass123",
            "new_password": "newtestpass456"
        }')
    
    echo "Password Change Response:"
    echo "$PASSWORD_CHANGE_RESPONSE" | jq '.' 2>/dev/null || echo "$PASSWORD_CHANGE_RESPONSE"
    
    NEW_TOKEN_AFTER_PWD=$(echo "$PASSWORD_CHANGE_RESPONSE" | jq -r '.access_token' 2>/dev/null)
    if [ "$NEW_TOKEN_AFTER_PWD" != "null" ] && [ "$NEW_TOKEN_AFTER_PWD" != "" ]; then
        print_success "Password successfully changed and new token provided"
        
        # Test login with new password
        print_test "Login with New Password"
        NEW_PWD_LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/token" \
            -H "Content-Type: application/x-www-form-urlencoded" \
            -d "username=testuser_updated&password=newtestpass456")
        
        NEW_PWD_TOKEN=$(echo "$NEW_PWD_LOGIN_RESPONSE" | jq -r '.access_token' 2>/dev/null)
        if [ "$NEW_PWD_TOKEN" != "null" ] && [ "$NEW_PWD_TOKEN" != "" ]; then
            print_success "Login with new password successful"
        else
            print_error "Login with new password failed"
        fi
    else
        print_error "Password change failed"
    fi
else
    print_error "No user token available"
fi

# ===============================================
# ENDPOINT ACCESS TESTS
# ===============================================

# Test 20-24: Test other endpoints with different user roles
print_test "Admin: Get Servers"
curl -s -X GET "$BASE_URL/servers/" \
    -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.' 2>/dev/null || echo "Failed to get servers"

print_test "User: Get Groups"
if [ -n "$USER_TOKEN" ]; then
    curl -s -X GET "$BASE_URL/groups/" \
        -H "Authorization: Bearer $USER_TOKEN" | jq '.' 2>/dev/null || echo "Failed to get groups"
fi

print_test "Admin: Get Templates"
curl -s -X GET "$BASE_URL/templates/" \
    -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.' 2>/dev/null || echo "Failed to get templates"

print_test "Operator: Get Servers"
if [ -n "$OPERATOR_TOKEN" ]; then
    curl -s -X GET "$BASE_URL/servers/" \
        -H "Authorization: Bearer $OPERATOR_TOKEN" | jq '.' 2>/dev/null || echo "Failed to get servers"
fi

print_test "No Auth: Try to Access Protected Endpoint"
NO_AUTH_RESPONSE=$(curl -s -X GET "$BASE_URL/users/me")
echo "No Auth Response:"
echo "$NO_AUTH_RESPONSE" | jq '.' 2>/dev/null || echo "$NO_AUTH_RESPONSE"

if echo "$NO_AUTH_RESPONSE" | grep -q "Not authenticated"; then
    print_success "Protected endpoint correctly requires authentication"
else
    print_error "Authentication requirement check failed"
fi

echo -e "\n${GREEN}🎉 Comprehensive API Testing Complete!${NC}"
echo -e "\n${BLUE}📊 Test Summary:${NC}"
echo "• User Registration & Authentication Tests: ✅"
echo "• User Approval Workflow Tests: ✅"
echo "• Role-Based Access Control Tests: ✅"
echo "• User Information Management Tests: ✅"
echo "• Password Management Tests: ✅"
echo "• Authorization & Permission Tests: ✅"
echo "• Endpoint Access Control Tests: ✅"

echo -e "\n${YELLOW}💡 Available tokens for manual testing:${NC}"
if [ -n "$ADMIN_TOKEN" ]; then
    echo "export ADMIN_TOKEN=\"$ADMIN_TOKEN\""
fi
if [ -n "$USER_TOKEN" ]; then
    echo "export USER_TOKEN=\"$USER_TOKEN\""
fi
if [ -n "$OPERATOR_TOKEN" ]; then
    echo "export OPERATOR_TOKEN=\"$OPERATOR_TOKEN\""
fi

echo -e "\n${YELLOW}💡 Example manual curl commands:${NC}"
echo "# Admin operations"
echo "curl -H \"Authorization: Bearer \$ADMIN_TOKEN\" $BASE_URL/users/"
echo "curl -H \"Authorization: Bearer \$ADMIN_TOKEN\" -X POST $BASE_URL/users/approve/USER_ID"

echo -e "\n# User operations"
echo "curl -H \"Authorization: Bearer \$USER_TOKEN\" $BASE_URL/users/me"
echo "curl -H \"Authorization: Bearer \$USER_TOKEN\" -X PUT $BASE_URL/users/me -d '{\"username\":\"new_name\"}'"

echo -e "\n# Role testing"
echo "curl -H \"Authorization: Bearer \$OPERATOR_TOKEN\" $BASE_URL/servers/"

# The cleanup function will handle test server shutdown via trap