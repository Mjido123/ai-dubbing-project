import streamlit as st
import subprocess
import os
import asyncio
import shutil
import time
import math
from groq import Groq
from deep_translator import GoogleTranslator
import edge_tts
import yt_dlp

# إعداد مفتاح واجهة Groq API
client = Groq(api_key="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")

st.set_page_config(page_title="نظام الدبلجة والتلخيص المتكامل", page_icon="🎬", layout="centered")

def download_youtube_video(youtube_url, output_path):
    ydl_opts = {
        'format': 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'ffmpeg_location': 'C:\\ffmpeg\\bin'
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
        return os.path.exists(output_path) and os.path.getsize(output_path) > 100000
    except Exception:
        return False

def extract_audio(video_input, audio_output):
    command = f'C:\\ffmpeg\\bin\\ffmpeg.exe -i "{video_input}" -q:a 0 -map a "{audio_output}" -y'
    subprocess.run(command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def get_audio_duration(audio_path):
    try:
        duration = float(subprocess.check_output(f'C:\\ffmpeg\\bin\\ffprobe.exe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{audio_path}"', shell=True).strip())
        return duration
    except:
        return 0

def transcribe_audio_groq(audio_input):
    file_size_mb = os.path.getsize(audio_input) / (1024 * 1024)
    
    if file_size_mb <= 24:
        with open(audio_input, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                file=(audio_input, audio_file.read()),
                model="whisper-large-v3",
                response_format="verbose_json"
            )
        return transcription.segments
    else:
        duration = get_audio_duration(audio_input)
        chunk_length = 900  
        total_chunks = math.ceil(duration / chunk_length)
        
        all_segments = []
        os.makedirs("audio_chunks_trans", exist_ok=True)
        
        for i in range(total_chunks):
            start_time = i * chunk_length
            chunk_path = f"audio_chunks_trans/chunk_{i}.mp3"
            cmd = f'C:\\ffmpeg\\bin\\ffmpeg.exe -ss {start_time} -i "{audio_input}" -t {chunk_length} -acodec copy "{chunk_path}" -y'
            subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if os.path.exists(chunk_path) and os.path.getsize(chunk_path) > 1000:
                with open(chunk_path, "rb") as audio_file:
                    try:
                        transcription = client.audio.transcriptions.create(
                            file=(chunk_path, audio_file.read()),
                            model="whisper-large-v3",
                            response_format="verbose_json"
                        )
                        for seg in transcription.segments:
                            seg_dict = seg if isinstance(seg, dict) else seg.__dict__
                            all_segments.append({
                                'start': seg_dict['start'] + start_time,
                                'end': seg_dict['end'] + start_time,
                                'text': seg_dict['text']
                            })
                    except Exception as e:
                        print(f"Error in chunk {i}: {e}")
                os.remove(chunk_path)
                
        shutil.rmtree("audio_chunks_trans", ignore_errors=True)
        return all_segments

def generate_video_summary(segments):
    full_text = " ".join([seg['text'] for seg in segments[:300]]) # حصرنا النصوص د الفيديوهات الطويلة بزاف
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "أنت خبير محترف في تلخيص محتوى الفيديوهات باللغة العربية الفصحى. "
                        "قم بقراءة النص التالي المأخوذ من فيديو بالإنجليزية، وصغ الملخص هكذا بالضبط:\n\n"
                        "1️⃣ في البداية، اكتب سطرين مركزين جداً تجيب فيهما على: ما هي أهم حاجة وأكبر فائدة سيستفيدها المشاهد من هذا الفيديو؟\n"
                        "2️⃣ تحتها مباشرة، اكتب سطر فرعي باسم '📍 أهم النقاط التي تم مناقشتها:' ثم اذكر أهم 3 إلى 5 نقاط أساسية تحدث عنها الفيديو على شكل عوارض واضحة ومختصرة.\n\n"
                        "تجنب المقدمات الطويلة والتزم بالاختصار والمفيد ديريكت."
                    )
                },
                {
                    "role": "user",
                    "content": f"إليك النص الكامل للفيديو: {full_text}"
                }
            ],
            temperature=0.4,
            max_tokens=800
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"لم نتمكن من توليد الخلاصة بسبب: {str(e)}"

def translate_segments_safe(segments, progress_bar):
    translated_segments = []
    translator = GoogleTranslator(source='en', target='ar')
    total_seg = len(segments)
    for i, seg in enumerate(segments):
        english_text = seg['text'].strip().replace("-->", "")
        if not english_text:
            translated_segments.append({"start": seg['start'], "end": seg['end'], "text": ""})
            continue
        try:
            arabic_text = translator.translate(english_text)
            time.sleep(0.2) # تسريع الترجمة للفيديوهات الطويلة
        except Exception: arabic_text = english_text 
        translated_segments.append({"start": seg['start'], "end": seg['end'], "text": arabic_text})
        progress_bar.progress((i + 1) / total_seg)
    return translated_segments

async def save_edge_tts(text, output_path, voice):
    if not text.strip(): return
    for attempt in range(3):
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 100: break 
        except: await asyncio.sleep(0.2)

async def generate_all_voices_async(segments, voice_id, batch_size=12): # تسريع توليد الصوت عبر زيادة الـ batch
    tasks = []
    for i, seg in enumerate(segments):
        tasks.append(save_edge_tts(seg['text'], f"audio_chunks/temp_{i}.mp3", voice_id))
        if len(tasks) == batch_size or i == len(segments) - 1:
            await asyncio.gather(*tasks)
            tasks = [] 
            await asyncio.sleep(0.2) 

def match_speed_and_render(segments):
    for i, seg in enumerate(segments):
        target_duration = seg['end'] - seg['start']
        temp_path = f"audio_chunks/temp_{i}.mp3"
        chunk_path = f"audio_chunks/chunk_{i}.wav"
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) < 100: continue
        try:
            actual_duration = float(subprocess.check_output(f'C:\\ffmpeg\\bin\\ffprobe.exe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{temp_path}"', shell=True).strip())
        except: actual_duration = target_duration
        if actual_duration > target_duration and target_duration > 0:
            speed_factor = actual_duration / target_duration
            if speed_factor > 2.0:
                subprocess.run(f'C:\\ffmpeg\\bin\\ffmpeg.exe -i "{temp_path}" -filter:a "atempo=2.0,atempo={speed_factor/2.0}" "{chunk_path}" -y', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.run(f'C:\\ffmpeg\\bin\\ffmpeg.exe -i "{temp_path}" -filter:a "atempo={speed_factor}" "{chunk_path}" -y', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(f'C:\\ffmpeg\\bin\\ffmpeg.exe -i "{temp_path}" "{chunk_path}" -y', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(temp_path): os.remove(temp_path)

def merge_audio_with_video_ffmpeg(video_input, segments, output_video_path):
    # 🔥 دالة معالجة المونتاج مصلحة ومؤمنة 100% للفيديوهات الطويلة والكبيرة
    try:
        video_duration = float(subprocess.check_output(f'C:\\ffmpeg\\bin\\ffprobe.exe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{video_input}"', shell=True).strip())
    except: video_duration = 0
    
    filter_complex = f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={video_duration}[a_silent];"
    amix_inputs = "[a_silent]"
    inputs_args = f'-i "{video_input}"'
    valid_chunks_count = 0
    
    for i, seg in enumerate(segments):
        chunk_path = f"audio_chunks/chunk_{i}.wav"
        if os.path.exists(chunk_path):
            inputs_args += f' -i "{chunk_path}"'
            delay_ms = int(seg['start'] * 1000)
            filter_complex += f"[{valid_chunks_count+1}:a]adelay={delay_ms}|{delay_ms},volume=2.5[delayed_{i}];"
            amix_inputs += f"[delayed_{i}]"
            valid_chunks_count += 1
            
    if valid_chunks_count == 0:
        # حماية ف حالة ما تلقى حتى مقطع صوتي واجد
        subprocess.run(f'C:\\ffmpeg\\bin\\ffmpeg.exe -i "{video_input}" -c copy -y "{output_video_path}"', shell=True)
        return

    filter_complex += f"{amix_inputs}amix=inputs={valid_chunks_count+1}:duration=first[out_audio]"
    
    with open("filter_complex.txt", "w", encoding="utf-8") as f: 
        f.write(filter_complex)
        
    # رندرة احترافية تضمن إنتاج الفيديو النهائي بدون تشنج
    cmd = f'C:\\ffmpeg\\bin\\ffmpeg.exe {inputs_args} -filter_complex_script "filter_complex.txt" -map 0:v -map "[out_audio]" -c:v copy -c:a aac -shortest -y "{output_video_path}"'
    subprocess.run(cmd, shell=True)
    
    if os.path.exists("filter_complex.txt"): os.remove("filter_complex.txt")

st.title("🎬 مصنع الدبلجة والتلخيص الآلي المتكامل")
st.markdown("اختر طريقة إدخال الفيديو اللّي بغيتي، والسيستم غايتولى كاع مراحل الدبلجة والتلخيص!")

input_source = st.radio("👇 اختر مصدر الفيديو:", ("🔗 رابط من يوتيوب", "💻 تحميل ملف فيديو من جهازك (MP4)"))

youtube_url = None
uploaded_file = None

if input_source == "🔗 رابط من يوتيوب":
    youtube_url = st.text_input("أدخل رابط فيديو يوتيوب هنا:", key="yt_url_key")
else:
    uploaded_file = st.file_uploader("ارفع ملف الفيديو من جهازك:", type=["mp4"])

voice_option = st.selectbox("🎙️ اختر خامة صوت الدبلجة:", ("صوت حامد (رجل)", "صوت شاكر (رجل)", "صوت سلمى (امرأة)"))

voice_mapping = {
    "صوت حامد (رجل)": "Microsoft Server Speech Text to Speech Voice (ar-SA, HamedNeural)",
    "صوت شاكر (رجل)": "Microsoft Server Speech Text to Speech Voice (ar-EG, ShakirNeural)",
    "صوت سلمى (امرأة)": "Microsoft Server Speech Text to Speech Voice (ar-EG, SalmaNeural)"
}

if st.button("🚀 ابدأ الدبلجة والتلخيص الآن", type="primary"):
    if input_source == "🔗 رابط من يوتيوب" and not youtube_url:
        st.warning("عافاك دخل الرابط أولاً!")
    elif input_source == "💻 تحميل ملف فيديو من جهازك (MP4)" and not uploaded_file:
        st.warning("عافاك اختار ملف الفيديو من جهازك أولاً!")
    else:
        input_video = "local_temp_video.mp4"
        output_audio = "local_temp_audio.mp3"
        final_video_path = "final_dubbed_video.mp4"
        
        if os.path.exists(input_video): os.remove(input_video)
        if os.path.exists(output_audio): os.remove(output_audio)
        if os.path.exists(final_video_path): os.remove(final_video_path)
        if os.path.exists("audio_chunks"): shutil.rmtree("audio_chunks")
        
        status = st.empty()
        video_ready = False
        
        if input_source == "🔗 رابط من يوتيوب":
            status.info("⏳ جاري سحب وتحميل الفيديو من يوتيوب تلقائياً...")
            video_ready = download_youtube_video(youtube_url, input_video)
        else:
            status.info("⏳ جاري حفظ ملف الفيديو المرفوع من جهازك...")
            with open(input_video, "wb") as f:
                f.write(uploaded_file.read())
            video_ready = os.path.exists(input_video)
            
        if video_ready:
            status.info("⏳ 1/5 جاري فصل وصيانة صوت الفيديو الأصلي...")
            extract_audio(input_video, output_audio)
            
            status.info("⏳ 2/5 جاري قراءة كلمات الفيديو بذكاء (معالجة الساعات الطويلة)...")
            segments = transcribe_audio_groq(output_audio)
            
            status.info("⏳ 3/5 جاري استخراج زبدة الفيديو والنقاط الأساسية...")
            summary_text = generate_video_summary(segments)
            
            status.info("⏳ 4/5 جاري توليد صياغة الأصوات العربية بالتوازي...")
            trans_progress = st.progress(0)
            final_segments = translate_segments_safe(segments, trans_progress)
            trans_progress.empty()
            
            os.makedirs("audio_chunks", exist_ok=True)
            asyncio.run(generate_all_voices_async(final_segments, voice_mapping[voice_option]))
            match_speed_and_render(final_segments)
            
            status.info("⏳ 5/5 جاري رندرة ومونتاج الفيلم النهائي (قد يستغرق بضع دقائق للفيديوهات الطويلة)...")
            merge_audio_with_video_ffmpeg(input_video, final_segments, final_video_path)
            
            # 🔥 حماية أمنية للتأكد من وجود الملف النهائي قبل عرضه لتفادي الـ FileNotFoundError
            if os.path.exists(final_video_path) and os.path.getsize(final_video_path) > 1000:
                status.success("🎉 مبروك! انتهت العملية بنجاح باهر!")
                st.markdown("### 💡 زبدة الفيديو وأهم النقاط:")
                st.info(summary_text)
                st.markdown("### 🎞️ الفيديو المدبلج بالكامل:")
                with open(final_video_path, "rb") as video_file:
                    st.video(video_file.read())
            else:
                status.error("❌ فشل الـ FFmpeg في إنتاج الفيديو النهائي. يرجى مراجعة حجم الملف أو تجربة مقطع أقصر.")
        else:
            status.error("❌ فشل معالجة الفيديو، يرجى التأكد من الملف أو الرابط المحطوط.")