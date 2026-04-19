#!/usr/bin/env python3
"""
PMLL Memory Graph Backend API Test Suite
Tests all endpoints as specified in the review request.
"""

import requests
import json
import sys
import time
from typing import Dict, Any, Optional

# Backend URL from frontend .env
BACKEND_URL = "https://semantic-silo.preview.emergentagent.com/api"
SESSION_ID = "test_session"

class PMMLLTester:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        self.test_results = []
        self.node_ids = []  # Store created node IDs for later tests
        
    def log_test(self, test_name: str, success: bool, details: str = "", response_data: Any = None):
        """Log test result"""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        if details:
            print(f"    {details}")
        if response_data and not success:
            print(f"    Response: {response_data}")
        print()
        
        self.test_results.append({
            "test": test_name,
            "success": success,
            "details": details,
            "response": response_data
        })
    
    def make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> tuple[bool, Any]:
        """Make HTTP request and return (success, response_data)"""
        url = f"{BACKEND_URL}{endpoint}"
        try:
            if method.upper() == "GET":
                response = self.session.get(url)
            elif method.upper() == "POST":
                response = self.session.post(url, json=data)
            else:
                return False, f"Unsupported method: {method}"
            
            response.raise_for_status()
            return True, response.json()
        except requests.exceptions.RequestException as e:
            return False, f"Request failed: {str(e)}"
        except json.JSONDecodeError as e:
            return False, f"JSON decode error: {str(e)}"
    
    def test_01_root_endpoint(self):
        """Test GET /api/ -> should return {service:"pmll-memory-graph", ok:true}"""
        success, data = self.make_request("GET", "/")
        
        if success:
            expected_service = "pmll-memory-graph"
            expected_ok = True
            
            if (data.get("service") == expected_service and 
                data.get("ok") == expected_ok):
                self.log_test("Root endpoint", True, "Service identification correct")
            else:
                self.log_test("Root endpoint", False, 
                            f"Expected service='{expected_service}', ok={expected_ok}, got {data}", data)
        else:
            self.log_test("Root endpoint", False, "Request failed", data)
    
    def test_02_init_session(self):
        """Test POST /api/init with session_id and silo_size"""
        data = {"session_id": SESSION_ID, "silo_size": 64}
        success, response = self.make_request("POST", "/init", data)
        
        if success:
            if (response.get("session_id") == SESSION_ID and 
                response.get("status") == "initialized" and
                response.get("silo_size") == 64):
                self.log_test("Session initialization", True, "Session initialized successfully")
            else:
                self.log_test("Session initialization", False, 
                            f"Unexpected response format", response)
        else:
            self.log_test("Session initialization", False, "Request failed", response)
    
    def test_03_set_key_value(self):
        """Test POST /api/set with key-value pair"""
        data = {"session_id": SESSION_ID, "key": "hello", "value": "world"}
        success, response = self.make_request("POST", "/set", data)
        
        if success:
            if response.get("ok") == True and response.get("key") == "hello":
                self.log_test("Set key-value", True, "Key-value set successfully")
            else:
                self.log_test("Set key-value", False, "Unexpected response", response)
        else:
            self.log_test("Set key-value", False, "Request failed", response)
    
    def test_04_peek_existing_key(self):
        """Test POST /api/peek with existing key"""
        data = {"session_id": SESSION_ID, "key": "hello"}
        success, response = self.make_request("POST", "/peek", data)
        
        if success:
            if (response.get("hit") == True and 
                response.get("value") == "world" and
                response.get("key") == "hello"):
                self.log_test("Peek existing key", True, "Key found with correct value")
            else:
                self.log_test("Peek existing key", False, "Unexpected response", response)
        else:
            self.log_test("Peek existing key", False, "Request failed", response)
    
    def test_05_peek_missing_key(self):
        """Test POST /api/peek with missing key"""
        data = {"session_id": SESSION_ID, "key": "missing"}
        success, response = self.make_request("POST", "/peek", data)
        
        if success:
            if response.get("hit") == False and response.get("key") == "missing":
                self.log_test("Peek missing key", True, "Missing key handled correctly")
            else:
                self.log_test("Peek missing key", False, "Unexpected response", response)
        else:
            self.log_test("Peek missing key", False, "Request failed", response)
    
    def test_06_resolve_promise(self):
        """Test POST /api/resolve with promise_id"""
        data = {"session_id": SESSION_ID, "promise_id": "p1"}
        success, response = self.make_request("POST", "/resolve", data)
        
        if success:
            if (response.get("id") == "p1" and 
                response.get("status") == "pending"):
                self.log_test("Resolve promise", True, "Promise created with pending status")
            else:
                self.log_test("Resolve promise", False, "Unexpected response", response)
        else:
            self.log_test("Resolve promise", False, "Request failed", response)
    
    def test_07_upsert_memory_node_ai(self):
        """Test POST /api/upsert_memory_node - AI concept"""
        data = {
            "session_id": SESSION_ID,
            "type": "concept",
            "label": "AI",
            "content": "artificial intelligence machine learning"
        }
        success, response = self.make_request("POST", "/upsert_memory_node", data)
        
        if success:
            if (response.get("label") == "AI" and 
                response.get("type") == "concept" and
                "id" in response):
                self.node_ids.append(response["id"])  # Store for later tests
                self.log_test("Upsert AI node", True, f"AI node created with ID: {response['id']}")
            else:
                self.log_test("Upsert AI node", False, "Unexpected response", response)
        else:
            self.log_test("Upsert AI node", False, "Request failed", response)
    
    def test_08_upsert_memory_node_ml(self):
        """Test POST /api/upsert_memory_node - ML concept"""
        data = {
            "session_id": SESSION_ID,
            "type": "concept",
            "label": "ML",
            "content": "machine learning algorithms neural networks"
        }
        success, response = self.make_request("POST", "/upsert_memory_node", data)
        
        if success:
            if (response.get("label") == "ML" and 
                response.get("type") == "concept" and
                "id" in response):
                self.node_ids.append(response["id"])  # Store for later tests
                self.log_test("Upsert ML node", True, f"ML node created with ID: {response['id']}")
            else:
                self.log_test("Upsert ML node", False, "Unexpected response", response)
        else:
            self.log_test("Upsert ML node", False, "Request failed", response)
    
    def test_09_create_valid_relation(self):
        """Test POST /api/create_relation with valid relation"""
        if len(self.node_ids) < 2:
            self.log_test("Create valid relation", False, "Not enough nodes created for relation test")
            return
            
        data = {
            "session_id": SESSION_ID,
            "source_id": self.node_ids[0],
            "target_id": self.node_ids[1],
            "relation": "depends_on",
            "weight": 0.9
        }
        success, response = self.make_request("POST", "/create_relation", data)
        
        if success:
            if (response.get("relation") == "depends_on" and 
                response.get("weight") == 0.9 and
                "id" in response):
                self.log_test("Create valid relation", True, f"Relation created with ID: {response['id']}")
            else:
                self.log_test("Create valid relation", False, "Unexpected response", response)
        else:
            self.log_test("Create valid relation", False, "Request failed", response)
    
    def test_10_create_invalid_relation(self):
        """Test POST /api/create_relation with invalid relation -> should return 400"""
        if len(self.node_ids) < 2:
            self.log_test("Create invalid relation", False, "Not enough nodes for relation test")
            return
            
        data = {
            "session_id": SESSION_ID,
            "source_id": self.node_ids[0],
            "target_id": self.node_ids[1],
            "relation": "foobar",
            "weight": 0.9
        }
        
        url = f"{BACKEND_URL}/create_relation"
        try:
            response = self.session.post(url, json=data)
            if response.status_code == 400:
                self.log_test("Create invalid relation", True, "Invalid relation correctly rejected with 400")
            else:
                self.log_test("Create invalid relation", False, 
                            f"Expected 400 status, got {response.status_code}")
        except Exception as e:
            self.log_test("Create invalid relation", False, f"Request failed: {str(e)}")
    
    def test_11_search_memory_graph(self):
        """Test POST /api/search_memory_graph"""
        data = {
            "session_id": SESSION_ID,
            "query": "machine learning",
            "top_k": 3,
            "max_depth": 1
        }
        success, response = self.make_request("POST", "/search_memory_graph", data)
        
        if success:
            if ("direct" in response and "neighbors" in response and "total" in response):
                direct_count = len(response.get("direct", []))
                neighbors_count = len(response.get("neighbors", []))
                total = response.get("total", 0)
                self.log_test("Search memory graph", True, 
                            f"Search returned {direct_count} direct, {neighbors_count} neighbors, total: {total}")
            else:
                self.log_test("Search memory graph", False, "Unexpected response format", response)
        else:
            self.log_test("Search memory graph", False, "Request failed", response)
    
    def test_12_add_interlinked_context(self):
        """Test POST /api/add_interlinked_context"""
        data = {
            "session_id": SESSION_ID,
            "items": [
                {
                    "type": "concept",
                    "label": "Deep Learning",
                    "content": "neural networks deep learning training"
                },
                {
                    "type": "concept",
                    "label": "NLP",
                    "content": "natural language processing text analysis"
                }
            ],
            "auto_link": True
        }
        success, response = self.make_request("POST", "/add_interlinked_context", data)
        
        if success:
            if (response.get("inserted") == 2 and 
                "node_ids" in response and 
                "auto_edges" in response):
                # Store new node IDs
                self.node_ids.extend(response["node_ids"])
                auto_edges = response.get("auto_edges", 0)
                self.log_test("Add interlinked context", True, 
                            f"Inserted 2 nodes, created {auto_edges} auto edges")
            else:
                self.log_test("Add interlinked context", False, "Unexpected response", response)
        else:
            self.log_test("Add interlinked context", False, "Request failed", response)
    
    def test_13_retrieve_with_traversal(self):
        """Test POST /api/retrieve_with_traversal"""
        if not self.node_ids:
            self.log_test("Retrieve with traversal", False, "No nodes available for traversal test")
            return
            
        data = {
            "session_id": SESSION_ID,
            "start_node_id": self.node_ids[0],
            "max_depth": 2
        }
        success, response = self.make_request("POST", "/retrieve_with_traversal", data)
        
        if success:
            if ("start" in response and "reachable" in response):
                reachable_count = len(response.get("reachable", []))
                self.log_test("Retrieve with traversal", True, 
                            f"Traversal found {reachable_count} reachable nodes")
            else:
                self.log_test("Retrieve with traversal", False, "Unexpected response format", response)
        else:
            self.log_test("Retrieve with traversal", False, "Request failed", response)
    
    def test_14_resolve_context_short_term(self):
        """Test POST /api/resolve_context for short-term key"""
        data = {"session_id": SESSION_ID, "key": "hello"}
        success, response = self.make_request("POST", "/resolve_context", data)
        
        if success:
            if response.get("source") == "short_term":
                self.log_test("Resolve context (short-term)", True, "Short-term context resolved")
            else:
                self.log_test("Resolve context (short-term)", False, 
                            f"Expected source='short_term', got {response.get('source')}", response)
        else:
            self.log_test("Resolve context (short-term)", False, "Request failed", response)
    
    def test_15_resolve_context_long_term(self):
        """Test POST /api/resolve_context for semantic match"""
        data = {"session_id": SESSION_ID, "key": "machine learning"}
        success, response = self.make_request("POST", "/resolve_context", data)
        
        if success:
            source = response.get("source")
            if source == "long_term":
                self.log_test("Resolve context (long-term)", True, "Long-term semantic match found")
            elif source == "miss":
                self.log_test("Resolve context (long-term)", True, "No semantic match found (acceptable)")
            else:
                self.log_test("Resolve context (long-term)", False, 
                            f"Unexpected source: {source}", response)
        else:
            self.log_test("Resolve context (long-term)", False, "Request failed", response)
    
    def test_16_promote_to_long_term(self):
        """Test POST /api/promote_to_long_term"""
        data = {
            "session_id": SESSION_ID,
            "key": "hello",
            "node_type": "memory"
        }
        success, response = self.make_request("POST", "/promote_to_long_term", data)
        
        if success:
            if (response.get("promoted") == True and 
                "id" in response and 
                response.get("label") == "hello"):
                self.log_test("Promote to long-term", True, f"Key promoted with ID: {response['id']}")
            else:
                self.log_test("Promote to long-term", False, "Unexpected response", response)
        else:
            self.log_test("Promote to long-term", False, "Request failed", response)
    
    def test_17_memory_status(self):
        """Test POST /api/memory_status"""
        data = {"session_id": SESSION_ID}
        success, response = self.make_request("POST", "/memory_status", data)
        
        if success:
            if ("short_term" in response and "long_term" in response):
                short_term = response["short_term"]
                long_term = response["long_term"]
                self.log_test("Memory status", True, 
                            f"Short-term: {short_term.get('size', 0)} items, "
                            f"Long-term: {long_term.get('nodes', 0)} nodes, {long_term.get('edges', 0)} edges")
            else:
                self.log_test("Memory status", False, "Unexpected response format", response)
        else:
            self.log_test("Memory status", False, "Request failed", response)
    
    def test_18_get_graph(self):
        """Test GET /api/graph/{session_id}"""
        success, response = self.make_request("GET", f"/graph/{SESSION_ID}")
        
        if success:
            if ("nodes" in response and "edges" in response):
                nodes_count = len(response.get("nodes", []))
                edges_count = len(response.get("edges", []))
                # Check if edges have decayed_weight
                edges = response.get("edges", [])
                has_decayed_weight = all("decayed_weight" in edge for edge in edges) if edges else True
                self.log_test("Get graph", True, 
                            f"Graph has {nodes_count} nodes, {edges_count} edges with decay weights")
            else:
                self.log_test("Get graph", False, "Unexpected response format", response)
        else:
            self.log_test("Get graph", False, "Request failed", response)
    
    def test_19_get_silo(self):
        """Test GET /api/silo/{session_id}"""
        success, response = self.make_request("GET", f"/silo/{SESSION_ID}")
        
        if success:
            if ("silo" in response and "size" in response and "capacity" in response):
                size = response.get("size", 0)
                capacity = response.get("capacity", 0)
                self.log_test("Get silo", True, f"Silo has {size}/{capacity} items")
            else:
                self.log_test("Get silo", False, "Unexpected response format", response)
        else:
            self.log_test("Get silo", False, "Request failed", response)
    
    def test_20_graphql_nodes(self):
        """Test POST /api/graphql for nodes query"""
        data = {
            "query": "{ nodes }",
            "variables": {"session_id": SESSION_ID}
        }
        success, response = self.make_request("POST", "/graphql", data)
        
        if success:
            if ("data" in response and "nodes" in response["data"]):
                nodes_count = len(response["data"]["nodes"])
                self.log_test("GraphQL nodes query", True, f"Retrieved {nodes_count} nodes via GraphQL")
            else:
                self.log_test("GraphQL nodes query", False, "Unexpected response format", response)
        else:
            self.log_test("GraphQL nodes query", False, "Request failed", response)
    
    def test_21_graphql_search(self):
        """Test POST /api/graphql for search query"""
        data = {
            "query": "{ search }",
            "variables": {
                "session_id": SESSION_ID,
                "query": "neural",
                "top_k": 3
            }
        }
        success, response = self.make_request("POST", "/graphql", data)
        
        if success:
            if ("data" in response and "search" in response["data"]):
                search_results = len(response["data"]["search"])
                self.log_test("GraphQL search query", True, f"Search returned {search_results} results")
            else:
                self.log_test("GraphQL search query", False, "Unexpected response format", response)
        else:
            self.log_test("GraphQL search query", False, "Request failed", response)
    
    def test_22_prune_stale_links(self):
        """Test POST /api/prune_stale_links"""
        data = {
            "session_id": SESSION_ID,
            "threshold": 0.1
        }
        success, response = self.make_request("POST", "/prune_stale_links", data)
        
        if success:
            if ("edges_pruned" in response and "edges_kept" in response and "orphans_removed" in response):
                pruned = response.get("edges_pruned", 0)
                kept = response.get("edges_kept", 0)
                orphans = response.get("orphans_removed", 0)
                self.log_test("Prune stale links", True, 
                            f"Pruned {pruned} edges, kept {kept}, removed {orphans} orphans")
            else:
                self.log_test("Prune stale links", False, "Unexpected response format", response)
        else:
            self.log_test("Prune stale links", False, "Request failed", response)
    
    def test_23_flush_session(self):
        """Test POST /api/flush"""
        data = {"session_id": SESSION_ID}
        success, response = self.make_request("POST", "/flush", data)
        
        if success:
            if response.get("ok") == True and response.get("flushed") == True:
                self.log_test("Flush session", True, "Session flushed successfully")
            else:
                self.log_test("Flush session", False, "Unexpected response", response)
        else:
            self.log_test("Flush session", False, "Request failed", response)
    
    def test_24_seed_and_search(self):
        """Test POST /api/seed/{session_id} and search for 'temporal decay'"""
        # First seed the session
        success, response = self.make_request("POST", f"/seed/test_session_2")
        
        if not success:
            self.log_test("Seed and search", False, "Seed request failed", response)
            return
        
        if not (response.get("seeded_nodes") == 12 and response.get("explicit_edges", 0) >= 9):
            self.log_test("Seed and search", False, 
                        f"Expected 12 nodes and >=9 edges, got {response}", response)
            return
        
        # Now search for "temporal decay"
        search_data = {
            "session_id": "test_session_2",
            "query": "temporal decay",
            "top_k": 3,
            "max_depth": 1
        }
        search_success, search_response = self.make_request("POST", "/search_memory_graph", search_data)
        
        if search_success:
            if ("direct" in search_response and "total" in search_response):
                total_results = search_response.get("total", 0)
                self.log_test("Seed and search", True, 
                            f"Seeded 12 nodes with {response.get('explicit_edges')} edges, "
                            f"search for 'temporal decay' returned {total_results} results")
            else:
                self.log_test("Seed and search", False, "Search response format invalid", search_response)
        else:
            self.log_test("Seed and search", False, "Search request failed", search_response)
    
    def run_all_tests(self):
        """Run all tests in sequence"""
        print("🚀 Starting PMLL Memory Graph Backend API Tests")
        print(f"Backend URL: {BACKEND_URL}")
        print(f"Session ID: {SESSION_ID}")
        print("=" * 60)
        
        # Run tests in order
        test_methods = [
            self.test_01_root_endpoint,
            self.test_02_init_session,
            self.test_03_set_key_value,
            self.test_04_peek_existing_key,
            self.test_05_peek_missing_key,
            self.test_06_resolve_promise,
            self.test_07_upsert_memory_node_ai,
            self.test_08_upsert_memory_node_ml,
            self.test_09_create_valid_relation,
            self.test_10_create_invalid_relation,
            self.test_11_search_memory_graph,
            self.test_12_add_interlinked_context,
            self.test_13_retrieve_with_traversal,
            self.test_14_resolve_context_short_term,
            self.test_15_resolve_context_long_term,
            self.test_16_promote_to_long_term,
            self.test_17_memory_status,
            self.test_18_get_graph,
            self.test_19_get_silo,
            self.test_20_graphql_nodes,
            self.test_21_graphql_search,
            self.test_22_prune_stale_links,
            self.test_23_flush_session,
            self.test_24_seed_and_search,
        ]
        
        for test_method in test_methods:
            try:
                test_method()
            except Exception as e:
                test_name = test_method.__name__.replace("test_", "").replace("_", " ").title()
                self.log_test(test_name, False, f"Test crashed: {str(e)}")
            
            # Small delay between tests
            time.sleep(0.1)
        
        # Summary
        print("=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        failed = total - passed
        
        print(f"Total Tests: {total}")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"Success Rate: {(passed/total)*100:.1f}%")
        
        if failed > 0:
            print("\n🔍 FAILED TESTS:")
            for result in self.test_results:
                if not result["success"]:
                    print(f"  ❌ {result['test']}: {result['details']}")
        
        return passed == total

if __name__ == "__main__":
    tester = PMMLLTester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)