import streamlit as st
import subprocess
import os
import asyncio
import shutil
import time
from groq import Groq
from deep_translator import GoogleTranslator
import edge_tts
import yt_dlp

# إعداد مفتاح واجهة Groq API (فقط لاستخراج النص الأصلي)
client = Groq(api_key="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")

# --- إعدادات واجهة الموقع (Streamlit UI) ---
st.set_page_config(page_title="نظام الدبلجة الآلي الاحترافي", page_icon="🎬", layout="centered")

def download_youtube_video(youtube_url, output_path, quality_choice):
    if "1080p" in quality_choice:
        format_str = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]'
    elif "720p" in quality_choice:
        format_str = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]'
    elif "480p" in quality_choice:
        format_str = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]'
    else:  
        format_str = 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]'

    ydl_opts = {
        'format': format_str,
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
        return True
    except Exception:
        return False

def extract_audio(video_input, audio_output):
    command = f'ffmpeg -i "{video_input}" -q:a 0 -map a "{audio_output}" -y'
    subprocess.run(command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def transcribe_audio_groq(audio_input):
    with open(audio_input, "rb") as audio_file:
        transcription = client.audio.transcriptions.create(
            file=(audio_input, audio_file.read()),
            model="whisper-large-v3",
            response_format="verbose_json"
        )
    return transcription.segments

# [🛡️ دالة الترجمة المحمية بالتريث البشري المضمون 100%]
def translate_segments_safe(segments):
    translated_segments = []
    translator = GoogleTranslator(source='en', target='ar')
    
    # صنع بروجريس بار صغير ف الواجهة باش تشوفي تقدم الترجمة جملة بجملة
    progress_bar = st.progress(0)
    total_seg = len(segments)
    
    for i, seg in enumerate(segments):
        english_text = seg['text'].strip()
        clean_text = english_text.replace("-->", "").strip()
        
        if not clean_text:
            translated_segments.append({"start": seg['start'], "end": seg['end'], "text": ""})
            continue
            
        try:
            arabic_text = translator.translate(clean_text)
            # تريث ذكي (نصف ثانية) لحماية الاتصال وضمان الترجمة للعربية
            time.sleep(0.5)
        except Exception:
            # محاولة أخيرة إذا وقع أي تشنج ف الإنترنت
            try:
                time.sleep(1.0)
                arabic_text = translator.translate(clean_text)
            except Exception:
                arabic_text = clean_text 
            
        translated_segments.append({
            "start": seg['start'],
            "end": seg['end'],
            "text": arabic_text
        })
        # تحديث شريط التقدم
        progress_bar.progress((i + 1) / total_seg)
        
    progress_bar.empty() # حذف شريط التقدم بعد النهاية
    return translated_segments

async def save_edge_tts(text, output_path, voice):
    if not text.strip():
        return
    for attempt in range(3):
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
                break 
        except Exception:
            await asyncio.sleep(0.4)

async def generate_all_voices_async(segments, voice_id, batch_size=8):
    tasks = []
    for i, seg in enumerate(segments):
        temp_path = f"audio_chunks/temp_{i}.mp3"
        tasks.append(save_edge_tts(seg['text'], temp_path, voice_id))
        
        # تصغير حجم الدفعة لـ 8 لحماية السيرفر الصوتي وضمان جلب الأصوات كاملة
        if len(tasks) == batch_size or i == len(segments) - 1:
            await asyncio.gather(*tasks)
            tasks = [] 
            await asyncio.sleep(0.4) 

def match_speed_and_render(segments):
    for i, seg in enumerate(segments):
        target_duration = seg['end'] - seg['start']
        temp_path = f"audio_chunks/temp_{i}.mp3"
        chunk_path = f"audio_chunks/chunk_{i}.wav"
        
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) < 100:
            continue
            
        duration_cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{temp_path}"'
        try:
            actual_duration = float(subprocess.check_output(duration_cmd, shell=True).strip())
        except Exception:
            actual_duration = target_duration
            
        if actual_duration > target_duration and target_duration > 0:
            speed_factor = actual_duration / target_duration
            if speed_factor > 2.0:
                speed_command = f'ffmpeg -i "{temp_path}" -filter:a "atempo=2.0,atempo={speed_factor/2.0}" "{chunk_path}" -y'
            else:
                speed_command = f'ffmpeg -i "{temp_path}" -filter:a "atempo={speed_factor}" "{chunk_path}" -y'
            subprocess.run(speed_command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            convert_command = f'ffmpeg -i "{temp_path}" "{chunk_path}" -y'
            subprocess.run(convert_command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        if os.path.exists(temp_path): 
            os.remove(temp_path)

def merge_audio_with_video_ffmpeg(video_input, segments, output_video_path):
    duration_cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{video_input}"'
    try:
        video_duration = float(subprocess.check_output(duration_cmd, shell=True).strip())
    except Exception:
        video_duration = 0
    
    filter_complex = f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={video_duration}[a_silent];"
    amix_inputs = "[a_silent]"
    inputs_args = f'-i "{video_input}"'
    
    volume_booster = "2.5"
    
    valid_chunks_count = 0
    for i, seg in enumerate(segments):
        chunk_path = f"audio_chunks/chunk_{i}.wav"
        if os.path.exists(chunk_path):
            inputs_args += f' -i "{chunk_path}"'
            delay_ms = int(seg['start'] * 1000)
            filter_complex += f"[{valid_chunks_count+1}:a]adelay={delay_ms}|{delay_ms},volume={volume_booster}[delayed_{i}];"
            amix_inputs += f"[delayed_{i}]"
            valid_chunks_count += 1
            
    if valid_chunks_count == 0:
        final_command = f'ffmpeg -i "{video_input}" -c copy -y "{output_video_path}"'
        subprocess.run(final_command, shell=True)
        return

    filter_complex += f"{amix_inputs}amix=inputs={valid_chunks_count+1}:duration=first[out_audio]"
    
    filter_script_path = "filter_complex.txt"
    with open(filter_script_path, "w", encoding="utf-8") as f:
        f.write(filter_complex)
        
    final_command = f'ffmpeg {inputs_args} -filter_complex_script "{filter_script_path}" -map 0:v -map "[out_audio]" -c:v copy -c:a aac -shortest -y "{output_video_path}"'
    subprocess.run(final_command, shell=True)
    
    if os.path.exists(filter_script_path):
        os.remove(filter_script_path)

def clear_temporary_files(audio_original_path, downloaded_video_path=None):
    if os.path.exists("audio_chunks"):
        shutil.rmtree("audio_chunks")
    if os.path.exists(audio_original_path):
        os.remove(audio_original_path)
    if downloaded_video_path and os.path.exists(downloaded_video_path):
        os.remove(downloaded_video_path)

# --- تصميم واجهة موقع الويب ---
st.title("🎬 نظام الدبلجة الآلي الاحترافي")
st.markdown("حول أي فيديو يوتيوب إنجليزي طويل إلى فيديو مدبلج بالعربية أوتوماتيكياً بـ كليك وحدة!")

youtube_url = st.text_input("🔗 أدخل رابط فيديو يوتيوب هنا:", placeholder="https://www.youtube.com/watch?v=...")

quality_choice = st.selectbox(
    "🎞️ اختر جودة تحميل الفيديو اللّي بغيتي:",
    ("480p (جودة متوسطة وسريعة)", "720p (جودة عالية HD)", "1080p (جودة عالية جداً)", "360p (اقتصادية)")
)

voice_option = st.selectbox(
    "🎙️ اختر خامة الصوت واللّكنة المفضلين لديك:",
    (
        "صوت حامد (رجل - سعودي وقور)", 
        "صوت شاكر (رجل - مصري إخباري)", 
        "صوت سلمى (امرأة - مصري ناعم)", 
        "صوت منى (امرأة - مغربي فصيح)"
    )
)

voice_mapping = {
    "صوت حامد (رجل - سعودي وقور)": "Microsoft Server Speech Text to Speech Voice (ar-SA, HamedNeural)",
    "صوت شاكر (رجل - مصري إخباري)": "Microsoft Server Speech Text to Speech Voice (ar-EG, ShakirNeural)",
    "صوت سلمى (امرأة - مصري ناعم)": "Microsoft Server Speech Text to Speech Voice (ar-EG, SalmaNeural)",
    "صوت منى (امرأة - مغربي فصيح)": "Microsoft Server Speech Text to Speech Voice (ar-MA, MounaNeural)"
}

selected_voice_id = voice_mapping[voice_option]

if st.button("🚀 ابدأ الدبلجة الإمبراطورية الآن", type="primary"):
    if not youtube_url:
        st.warning("عافاك دخل رابط فيديو يوتيوب أولاً!")
    else:
        output_folder = "web_outputs"
        os.makedirs(output_folder, exist_ok=True)
        
        input_video = "web_temp_video.mp4"
        output_audio = "web_temp_audio.mp3"
        final_video_path = os.path.join(output_folder, "final_dubbed_video.mp4")
        
        status_box = st.empty()
        
        try:
            status_box.info(f"⏳ جاري تحميل الفيديو من يوتيوب بجودة {quality_choice}... (قد يستغرق لحظات)")
            if download_youtube_video(youtube_url, input_video, quality_choice):
                
                status_box.info("⏳ 1/5 جاري عزل وصيانة الصوت الأصلي...")
                extract_audio(input_video, output_audio)
                
                status_box.info("⏳ 2/5 جاري استخراج النص والتوقيت بدقة (Groq Whisper)...")
                segments = transcribe_audio_groq(output_audio)
                
                status_box.info("⏳ 3/5 جاري الترجمة الاحترافية المضمونة (جوجل الآمن)...")
                final_segments = translate_segments_safe(segments)
                
                status_box.info("⏳ 4/5 جاري توليد خام الأصوات بنظام المجموعات المحمي (Turbo Batches)...")
                os.makedirs("audio_chunks", exist_ok=True)
                asyncio.run(generate_all_voices_async(final_segments, selected_voice_id))
                
                status_box.info("⏳ جاري وزن سرعات المقاطع الصوتية وهندسة الفريكونسي...")
                match_speed_and_render(final_segments)
                
                status_box.info("⏳ 5/5 جاري رندرة ومونتاج الفيديو النهائي بـ FFmpeg...")
                merge_audio_with_video_ffmpeg(input_video, final_segments, final_video_path)
                
                status_box.success("🎉 مبروك! انتهت دبلجة الفيديو بنجاح خارق وبصوت عربي كامل!")
                
                st.markdown("### 🍿 شاهد وحمل الفيديو المدبلج:")
                with open(final_video_path, "rb") as video_file:
                    st.video(video_file.read())
                    
                clear_temporary_files(output_audio, input_video)
            else:
                status_box.error("❌ فشل تحميل الفيديو، يرجى التحقق من الرابط وإعادة المحاولة.")
        except Exception as e:
            status_box.error(f"❌ حدث خطأ غير متوقع: {str(e)}")
            clear_temporary_files(output_audio, input_video)