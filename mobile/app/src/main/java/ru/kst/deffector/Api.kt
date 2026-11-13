package ru.kst.deffector

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import retrofit2.HttpException
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import retrofit2.http.*
import java.net.Proxy
import java.util.concurrent.TimeUnit

interface Api {
    @GET("api/health") suspend fun health(): Health
    @GET("api/equipment") suspend fun list(@Query("q") q: String): EquipmentList
    @GET("api/equipment/lookup") suspend fun lookup(
        @Query("qr") qr: String? = null, @Query("serial") serial: String? = null,
        @Query("marking") marking: String? = null
    ): LookupResult
    @Multipart @POST("api/identify/image") suspend fun identify(@Part image: MultipartBody.Part): IdentifyResult
    @GET("api/equipment/{id}") suspend fun card(@Path("id") id: String): EquipmentCard
    @GET("api/equipment/{id}/attention") suspend fun attention(@Path("id") id: String): AttentionList
    @Multipart @POST("api/equipment/{id}/detect") suspend fun detect(
        @Path("id") id: String, @Part image: MultipartBody.Part
    ): DetectResult
    @GET("api/equipment/{id}/components/{cid}") suspend fun component(
        @Path("id") id: String, @Path("cid") cid: String
    ): Component
    @Multipart @POST("api/equipment/{id}/components/{cid}/analyze") suspend fun analyze(
        @Path("id") id: String, @Path("cid") cid: String, @Part image: MultipartBody.Part,
        @Part("detection_confidence") confidence: RequestBody
    ): Component
    @POST("api/equipment/{id}/inspections") suspend fun inspect(
        @Path("id") id: String, @Body body: InspectionIn
    ): InspectionResult
    @GET("api/equipment/{id}/history") suspend fun history(@Path("id") id: String): History
}

object Network {
    val json = Json { ignoreUnknownKeys = false; encodeDefaults = true }

    // Числовой локальный адрес исключает обращения к внешнему DNS.
    fun address(value: String): HttpUrl {
        val url = (value.trim().trimEnd('/') + "/").toHttpUrl()
        require(url.scheme == "http" && url.encodedPath == "/" && url.query == null &&
            url.fragment == null && url.username.isEmpty() && url.password.isEmpty()) {
            "Укажите http://локальный-IP:порт без пути и пароля"
        }
        val octets = url.host.split('.')
        require(octets.size == 4 && octets.all { it.toIntOrNull() in 0..255 }) { "Нужен числовой локальный IPv4-адрес ПК" }
        val parts = octets.map { it.toInt() }
        require(parts.size == 4 && (parts[0] == 10 || parts[0] == 127 ||
            (parts[0] == 192 && parts[1] == 168) || (parts[0] == 172 && parts[1] in 16..31))) {
            "Нужен локальный IPv4-адрес ПК: 10.x.x.x, 172.16–31.x.x или 192.168.x.x"
        }
        return url
    }

    fun create(value: String): Api {
        val url = address(value)
        val client = OkHttpClient.Builder().proxy(Proxy.NO_PROXY)
            .followRedirects(false).followSslRedirects(false)
            .connectTimeout(4, TimeUnit.SECONDS).readTimeout(25, TimeUnit.SECONDS)
            .callTimeout(30, TimeUnit.SECONDS)
            .addInterceptor { chain ->
                val target = chain.request().url
                check(target.host == url.host && target.port == url.port && target.scheme == url.scheme)
                chain.proceed(chain.request())
            }.build()
        return Retrofit.Builder().baseUrl(url).client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType())).build().create(Api::class.java)
    }

    fun image(bytes: ByteArray) = MultipartBody.Part.createFormData(
        "image", "frame.jpg", bytes.toRequestBody("image/jpeg".toMediaType())
    )

    fun message(t: Throwable): String = when (t) {
        is HttpException -> runCatching {
            json.parseToJsonElement(t.response()?.errorBody()?.string().orEmpty())
                .jsonObject["error"]!!.jsonObject["message"]!!.jsonPrimitive.content
        }.getOrDefault("Сервер ответил ошибкой ${t.code()}")
        is java.net.SocketTimeoutException -> "Сервер не ответил вовремя. Проверьте стенд и повторите."
        is java.io.IOException -> "Нет связи с ПК. Проверьте адрес сервера и подключение к общей сети."
        else -> t.message ?: "Не удалось выполнить запрос"
    }
}
