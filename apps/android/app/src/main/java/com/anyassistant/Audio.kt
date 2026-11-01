// The microphone and the speaker: what it hears goes to the Mac as 16-bit mono PCM at 48 kHz
// (20 ms pieces), and what the Mac says, the same, is played in order. In «communication» mode,
// with Android's echo canceller where the phone has one, so it can hear you while it talks;
// through the loudspeaker.

package com.anyassistant

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import android.os.Build
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlin.math.abs

class Audio(private val context: Context) {
    private val rate = 48000
    private val piece = 960  // 20 ms
    private var recorder: AudioRecord? = null
    private var track: AudioTrack? = null
    private val queue = LinkedBlockingQueue<ShortArray>()
    @Volatile private var running = false
    @Volatile private var generation = 0  // a hush drops what was queued before it
    private var threads = listOf<Thread>()

    /** How loud its own voice is now (0…1), for the face. */
    var onSpeech: ((Float) -> Unit)? = null

    val isRunning get() = running

    @SuppressLint("MissingPermission")  // asked for before starting
    fun start(heard: (ByteArray, Float) -> Unit) {
        if (running) return
        val manager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        manager.mode = AudioManager.MODE_IN_COMMUNICATION
        loudspeaker(manager)
        val inSize = maxOf(AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT), piece * 4)
        val record = AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION, rate, AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT, inSize)
        if (record.state != AudioRecord.STATE_INITIALIZED) { record.release(); return }
        if (AcousticEchoCanceler.isAvailable()) AcousticEchoCanceler.create(record.audioSessionId)?.enabled = true
        if (NoiseSuppressor.isAvailable()) NoiseSuppressor.create(record.audioSessionId)?.enabled = true
        val outSize = maxOf(AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT), piece * 8)
        val player = AudioTrack.Builder()
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            .setAudioFormat(AudioFormat.Builder().setSampleRate(rate).setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
            .setBufferSizeInBytes(outSize)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
        recorder = record
        track = player
        running = true
        record.startRecording()
        player.play()
        val listen = Thread {
            val samples = ShortArray(piece)
            val bytes = ByteArray(piece * 2)
            while (running) {
                val count = record.read(samples, 0, piece)
                if (count <= 0) continue
                var peak = 0
                for (i in 0 until count) {
                    val s = samples[i].toInt()
                    peak = maxOf(peak, abs(s))
                    bytes[2 * i] = (s and 0xff).toByte()
                    bytes[2 * i + 1] = (s shr 8 and 0xff).toByte()
                }
                heard(bytes.copyOf(count * 2), peak / 32768f)
            }
        }
        val speak = Thread {
            while (running) {
                val samples = queue.poll(100, TimeUnit.MILLISECONDS)
                if (samples == null) { onSpeech?.invoke(0f); continue }
                val mine = generation
                var at = 0
                while (at < samples.size && running && mine == generation) {  // in 20 ms steps: a hush cuts in at once
                    val count = minOf(piece, samples.size - at)
                    var peak = 0
                    for (i in at until at + count) peak = maxOf(peak, abs(samples[i].toInt()))
                    onSpeech?.invoke(peak / 32768f)
                    player.write(samples, at, count)
                    at += count
                }
            }
        }
        threads = listOf(listen, speak).onEach { it.isDaemon = true; it.start() }
    }

    /** The loudspeaker, not the earpiece (communication mode would choose the earpiece). */
    private fun loudspeaker(manager: AudioManager) {
        if (Build.VERSION.SDK_INT >= 31) {
            manager.availableCommunicationDevices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER }
                ?.let { manager.setCommunicationDevice(it) }
        } else {
            @Suppress("DEPRECATION")
            manager.isSpeakerphoneOn = true
        }
    }

    /** Its voice: 16-bit mono PCM at 48 kHz (little-endian), after what is already queued. */
    fun play(pcm: ByteArray) {
        if (!running || pcm.size < 2) return
        val samples = ShortArray(pcm.size / 2) { i -> ((pcm[2 * i].toInt() and 0xff) or (pcm[2 * i + 1].toInt() shl 8)).toShort() }
        queue.put(samples)
    }

    /** Interrupted: what was left to say isn't said. */
    fun hush() {
        generation++
        queue.clear()
        track?.let { runCatching { it.pause(); it.flush(); it.play() } }
    }

    fun stop() {
        if (!running) return
        running = false
        threads.forEach { runCatching { it.join(500) } }
        queue.clear()
        recorder?.let { runCatching { it.stop() }; it.release() }
        track?.let { runCatching { it.stop() }; it.release() }
        recorder = null
        track = null
        onSpeech?.invoke(0f)
        val manager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        if (Build.VERSION.SDK_INT >= 31) manager.clearCommunicationDevice() else earpiece(manager)
        manager.mode = AudioManager.MODE_NORMAL
    }

    @Suppress("DEPRECATION")
    private fun earpiece(manager: AudioManager) { manager.isSpeakerphoneOn = false }
}
