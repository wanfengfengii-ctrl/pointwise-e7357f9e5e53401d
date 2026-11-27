from catalog.audio_metadata import measure_audio
from catalog.credits import make_credit
from catalog.recordings import RecordingStore
from catalog.wave_source import read_pcm_wave


def submit_recording(store: RecordingStore, actor_id, credit, audio):
    attribution = make_credit(actor_id, credit)
    metadata = measure_audio(read_pcm_wave(audio))
    return store.insert(attribution, metadata, audio)
