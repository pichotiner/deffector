package ru.kst.deffector

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.decodeFromString
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.TimeUnit

class ApiTest {
    private inline fun <reified T> fixture(name: String): T = Network.json.decodeFromString(
        javaClass.classLoader!!.getResource("$name.json")!!.readText())

    @Test fun parsesActualBackendResponses() {
        assertEquals("ok", fixture<Health>("health").status)
        assertEquals(2, fixture<EquipmentList>("equipment-list").items.size)
        assertEquals("PU-001", fixture<LookupResult>("lookup").equipment_id)
        assertFalse(fixture<LookupResult>("lookup-miss").found)
        val card = fixture<EquipmentCard>("card")
        assertTrue(card.components.any { it.resource.status == "insufficient_data" })
        assertTrue(card.parameters.any { it.status == "deviation" })
        assertEquals("PU-002", fixture<EquipmentCard>("card-second").id)
        assertTrue(fixture<AttentionList>("attention").items.isNotEmpty())
        assertTrue(fixture<DetectResult>("detect").detections.all { it.bbox.size == 4 })
        assertTrue(fixture<IdentifyResult>("identify").candidates.isNotEmpty())
        assertEquals("C-02", fixture<Component>("component").id)
        assertNotEquals("not_analyzed", fixture<Component>("analyze").visual.category)
        assertEquals("defect", fixture<InspectionResult>("inspection").inspection.type)
        assertTrue(fixture<History>("history").items.any { it.comment == "Тест мобильного клиента" })
        val login = fixture<LoginResult>("login")
        assertTrue(login.token.isNotBlank())
        assertEquals("master", login.user.role)
        assertEquals(listOf("view", "inspect", "report"), fixture<User>("me").permissions)
    }
    @Test fun tokenIsSentOnlyAfterLogin() = runBlocking {
        MockWebServer().use { server ->
            val health = javaClass.classLoader!!.getResource("health.json")!!.readText()
            repeat(2) { server.enqueue(MockResponse().setHeader("Content-Type", "application/json").setBody(health)) }
            server.start()
            var token: String? = null
            val api = Network.create(server.url("/").newBuilder().host("127.0.0.1").build().toString()) { token }
            api.health()
            assertNull(server.takeRequest(2, TimeUnit.SECONDS)!!.getHeader("Authorization"))
            token = "abc"
            api.health()
            assertEquals("Bearer abc", server.takeRequest(2, TimeUnit.SECONDS)!!.getHeader("Authorization"))
        }
    }
    @Test fun reportIsDownloadedAsFile() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setHeader("Content-Type", "application/pdf").setBody("%PDF-1.4 test"))
            server.start()
            val api = Network.create(server.url("/").newBuilder().host("127.0.0.1").build().toString()) { "abc" }
            assertEquals("%PDF-1.4 test", api.report("PU-001", "pdf").use { it.string() })
            val request = server.takeRequest(2, TimeUnit.SECONDS)!!
            assertEquals("/api/equipment/PU-001/report?format=pdf", request.path)
            assertEquals("Bearer abc", request.getHeader("Authorization"))
        }
    }
    @Test fun localAddressOnly() {
        listOf("http://192.168.1.2:8000", "http://172.20.10.2:8000", "http://10.0.2.2:8000").forEach { Network.address(it) }
        listOf("https://192.168.1.2", "http://example.com", "http://8.8.8.8", "http://192.168.1.2/path", "http://user:pass@10.0.0.1", "http://10.0.0.1.example.com").forEach {
            assertTrue(it, runCatching { Network.address(it) }.isFailure)
        }
    }
    @Test fun redirectToInternetIsNotFollowed() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", "http://example.com"))
            server.start()
            val failure = runCatching { Network.create(server.url("/").newBuilder().host("127.0.0.1").build().toString()).health() }.exceptionOrNull()
            assertTrue(failure is retrofit2.HttpException)
            assertEquals(1, server.requestCount)
        }
    }
    @Test fun multipartFieldAndRequestPathMatchContract() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setHeader("Content-Type", "application/json")
                .setBody(javaClass.classLoader!!.getResource("detect.json")!!.readText()))
            server.start()
            Network.create(server.url("/").newBuilder().host("127.0.0.1").build().toString()).detect("PU-001", Network.image(byteArrayOf(1, 2, 3)))
            val request = server.takeRequest(2, TimeUnit.SECONDS)!!
            assertEquals("/api/equipment/PU-001/detect", request.path)
            assertTrue(request.body.readUtf8().contains("name=\"image\"; filename=\"frame.jpg\""))
        }
    }
}
