# Last.fm API Setup Guide

## 🔑 **Getting Your Last.fm API Key**

### **Step 1: Create Last.fm Account**

1. Visit [Last.fm](https://www.last.fm)
2. Sign up for a free account (or log in if you have one)

### **Step 2: Apply for API Access**

1. Go to [Last.fm API page](https://www.last.fm/api)
2. Click **"Get an API account"**
3. Fill out the application form:
   - **Application name**: `WAV-to-FLAC-Converter`
   - **Description**: `Personal music metadata enhancement tool`
   - **Application homepage**: Leave blank or use your GitHub
   - **Contact email**: Your email address

### **Step 3: Get Your API Credentials**

After approval (usually instant), you'll get:

- **API Key**: A long string like `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6`
- **Secret**: Another string (optional for read-only access)

## ⚙️ **Configure the Enhanced Script**

### **Option 1: Edit the Script** *(Recommended)*

1. Open `wav_to_flac_converter_enhanced.py`
2. Find these lines near the top:

   ```python
   LASTFM_API_KEY = "YOUR_LASTFM_API_KEY"
   LASTFM_API_SECRET = "YOUR_LASTFM_SECRET"
   ```

3. Replace with your actual keys:

   ```python
   LASTFM_API_KEY = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
   LASTFM_API_SECRET = "your_secret_here"
   ```

### **Option 2: Environment Variables** *(Advanced)*

Set environment variables (more secure):

```bash
# Windows
set LASTFM_API_KEY=your_key_here
set LASTFM_API_SECRET=your_secret_here

# Linux/Mac
export LASTFM_API_KEY=your_key_here
export LASTFM_API_SECRET=your_secret_here
```

## 🧪 **Test the Integration**

Run the enhanced script and check the logs:

```bash
python wav_to_flac_converter_enhanced.py "test_folder" --fingerprinting
```

Look for:

- ✅ `[LASTFM] Last.fm API enabled`
- ❌ `[LASTFM] Last.fm API key not configured`

## 🎯 **What Last.fm Provides**

### **Enhanced Metadata**

- **Artist name corrections** ("3 en linea" → "3 En Línea")
- **Proper capitalization** and formatting
- **Genre tags** from user community
- **Popularity data** (playcount, listeners)

### **Perfect for Mexican Music**

- **Better international coverage** than MusicBrainz alone
- **User-generated data** includes regional artists
- **Artist correction service** helps with spelling variations
- **Genre classification** from real users

### **Fallback Strategy**

```
1. Check existing metadata
2. Try album-based lookup (MusicBrainz)
3. Try individual track search (MusicBrainz)  
4. Try audio fingerprinting (AcoustID)
5. Try Last.fm text search ⭐ NEW
6. Use directory structure
```

## 🔄 **How It Improves Your Collection**

### **Before:**

```
Artist: 3 en línea
Album: Antro-Pop
Title: Track03
Genre: (empty)
```

### **After with Last.fm:**

```
Artist: 3 En Línea
Album: Antro-Pop  
Title: La Cumbia del Corazón
Genre: Latin Pop, Mexican, Cumbia
Playcount: 15,420
```

## 🚨 **Troubleshooting**

### **"Last.fm API key not configured"**

- Make sure you replaced `YOUR_LASTFM_API_KEY` with your actual key
- Check for typos in the API key

### **"pylast.WSError: Invalid API key"**

- Double-check your API key is correct
- Make sure you copied the entire key

### **"Track not found"**

- Normal for rare tracks - script will try other methods
- Last.fm works best with known artists/songs

### **Rate Limiting**

- Last.fm is generous with rate limits
- No special handling needed for normal use

## 💡 **Tips for Best Results**

1. **Use with fingerprinting**: `--fingerprinting` for maximum coverage
2. **Check logs**: Monitor what each service finds
3. **International artists**: Last.fm often has better coverage than MusicBrainz
4. **Genre enhancement**: Last.fm adds community-generated genres

---

**Ready to enhance your Mexican music collection!** 🎵🇲🇽
