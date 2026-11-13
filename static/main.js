// ====================================================================
// rendering helpers
// ====================================================================
function renderTitle(title, preview=false) {
  let id = 'video-title';
  if (preview) {
    id = 'preview-' + id;
  }
  const titleElement = document.getElementById(id);
  titleElement.removeAttribute('hidden');
  titleElement.textContent = title
}

function renderThumbnail(thumbnailUrl, preview=false) {
  if (!thumbnailUrl) {
    return;
  }
  let id = 'video-thumbnail';
  if (preview) {
    id = 'preview-' + id;
  }
  const thumbnailElement = document.getElementById(id);
  thumbnailElement.removeAttribute('hidden');
  console.log({'thumbnailUrl.startsWith("/")': thumbnailUrl.startsWith("/"), thumbnailUrl});
  if (thumbnailUrl.startsWith("/")) {
    let url = new URL('/api/video/thumbnail/', window.location.href);
    url.searchParams.append('thumbnail_path', encodeURIComponent(thumbnailUrl));
    thumbnailElement.src = url.href;
  } else {
    thumbnailElement.src = thumbnailUrl;
  }
}

function renderSubmitResult(worked) {
  const textContent = worked ? "Success!" : "Failed :(";
  const backgroundColor = worked ? "#137000" : "#910700";
  const maybeTextColor = worked ? "" : "white";

  let submitButton = document.getElementById('submit');
  submitButton.textContent = textContent;
  submitButton.style.backgroundColor = backgroundColor;
  submitButton.style.color = maybeTextColor;
  submitButton.setAttribute("disabled", true);

  setTimeout(() => {
    submitButton.textContent = "go";
    submitButton.style.backgroundColor = "";
    submitButton.removeAttribute("disabled", true);
  }, 1500);
}

async function maybeRenderVideoMetadata(event, override=false) {
  const { value: currentUrl } = event.target;
  const urlType = getUrlType(currentUrl);

  let durationToggleButton = document.getElementById('get-video-seconds');
  let loopVideoButton = document.getElementById('loop-video');
  let submitButton = document.getElementById('submit');
  let videoInPlaylistPrompt = document.getElementById('video-in-playlist-prompt');
  let startOffsetInput = document.getElementById('start-offset-seconds');
  const playlistInput = document.getElementById('is-playlist');

  // initial case, text always says go and the prompt is always hidden
  submitButton.textContent = 'go';
  videoInPlaylistPrompt.setAttribute('hidden', true);
  loopVideoButton.checked = false;
  loopVideoButton.textContent = 'loop video?';
  playlistInput.checked = false;
  if (urlType === URL_TYPE.INVALID) {
    durationToggleButton.setAttribute('hidden', true);
    loopVideoButton.setAttribute('hidden', true);
    submitButton.setAttribute('hidden', true);
    showVideoPreview(false);
    showNowPlaying(true);
    return;
  } else if (urlType === URL_TYPE.VIDEO_IN_PLAYLIST) {
    loopVideoButton.textContent = 'loop playlist?';
    submitButton.textContent = 'start playlist!';
    videoInPlaylistPrompt.removeAttribute('hidden');
    playlistInput.checked = true;
  } else if (urlType === URL_TYPE.PLAYLIST) {
    loopVideoButton.textContent = 'loop playlist?';
    submitButton.textContent = 'start playlist!';
    playlistInput.checked = true;
  } else if (urlType === URL_TYPE.VIDEO) {
    loopVideoButton.textContent = 'loop video?'
  }

  // we dont let playlists specify a start offset, so if the given url is
  // a playlist, hide the start offset input
  if (playlistInput.checked) {
    startOffsetInput.setAttribute('hidden', playlistInput.checked);
    durationToggleButton.setAttribute('hidden', playlistInput.checked);
  } else {
    durationToggleButton.removeAttribute('hidden');
  }
  showNowPlaying(false);

  loopVideoButton.removeAttribute('hidden');
  submitButton.removeAttribute('hidden');
  const metadataRequestedInput = document.getElementById('was-metadata-requested');
  const {
    checked: dataPreviouslyRendered
  } = metadataRequestedInput;
  // we skip showing a video's metadata if we have rendered a url before
  if (dataPreviouslyRendered && !override) {
    return;
  }
  const title = await getVideoTitle(currentUrl);
  const thumbnail = await getVideoThumbnail(currentUrl);
  if (title) {
    renderTitle(title, true);
  }
  if (thumbnail) {
    renderThumbnail(thumbnail, true);
    showVideoPreview(true);
  }
  metadataRequestedInput.checked = true;
}

function hideOrShowDurationSlider(event) {
  const { value: currentUrl } = event.target;
  const {
    value: lastUrlThatDurationWasRequested
  } = document.getElementById('last-requested-duration-url');

  const durationWasPreviouslyRequested = !!lastUrlThatDurationWasRequested;
  const weHaveSeenThisUrl =
    getBaseUrl(lastUrlThatDurationWasRequested) === getBaseUrl(currentUrl);
  let secondsInput = document.getElementById("start-offset-seconds");
  if (durationWasPreviouslyRequested && weHaveSeenThisUrl) {
    secondsInput.removeAttribute('hidden');
    humanizeTimeSliderValue({
      target: {
        value: secondsInput.value,
        max: secondsInput.max,
      },
    });
  } else {
    document.getElementById('humanized-start-time').textContent = '';
    secondsInput.setAttribute('hidden', 'true');
  }
}

function toggleVideoLoop() {
  let loopVideoInput = document.getElementById('loop-video');
  loopVideoInput.checked = !loopVideoInput.checked;
  const playlistInput = document.getElementById('is-playlist');
  const {
    checked: isPlaylistUrlEntered,
  } = playlistInput;
  const playlistOrVideo = isPlaylistUrlEntered ? 'playlist' : 'video';
  if (loopVideoInput.checked) {
    document.getElementById('loop-video').textContent = `${playlistOrVideo} will loop!`;
    loopVideoInput.style.backgroundColor = "#01488a";
  } else {
    document.getElementById('loop-video').textContent = `loop ${playlistOrVideo}?`;
    loopVideoInput.style.backgroundColor = "transparent";
  }
}

function showNowPlaying(visible=false) {
  const thereIsSomethingToShow = !!document.getElementById('video-title').textContent;
  const height = (thereIsSomethingToShow && visible) ? "max-height: 30em" : "max-height:0px";
  document.querySelector('.now-playing').setAttribute("style", height);
}

function showVideoPreview(visible=false) {
  const height = visible ? "max-height: 30em" : "max-height:0px";
  document.querySelector('.preview-video').setAttribute("style", height);
}

// ====================================================================
// Requests to APIs
// ====================================================================
const stream = window.location.host.split('.')[0];

async function handleSubmit(e) {
  const { value: clipboardContents } = document.getElementById('url');
  const startOffsetInput = document.getElementById('start-offset-seconds');
  const { hidden: startOffsetHidden } = startOffsetInput;
  const { checked: loop } = document.getElementById('loop-video');
  let maybestartOffsetSeconds = null;
  if (!startOffsetHidden) {
    maybestartOffsetSeconds = Number(startOffsetInput.value);
  }

  // reset metadata state, after submitting we can request
  // a url's thumbnail and title again
  const metadataRequestedInput = document.getElementById('was-metadata-requested');
  metadataRequestedInput.checked = false;

  const url = new URL('/api/play', window.location.href);
  fetch(url.href, {
    method: 'POST',
    body: JSON.stringify({
      url: clipboardContents,
      startOffsetSeconds: maybestartOffsetSeconds,
      loop,
      stream,
    })
  })
    .then(() => {
      renderSubmitResult(true);
    })
    .catch(() => {
      renderSubmitResult(false);
    })
}

function getServerState() {
  return new Promise(resolve => {
    const url = new URL('/api/state', window.location.href);
    url.searchParams.append("stream", stream);
    fetch(url.href, {})
      .then(response => response.json())
      .then(data => resolve(data))
      .catch(data => resolve(false));
  });
}

function handleStop() {
  const url = new URL('/api/stop', window.location.href);
  fetch(url.href, {
    method: 'POST',
    body: JSON.stringify({
      stream,
    })
  })
    .then(response => response.json())
    .then((data) => {
      if (data.success) {
        document.getElementById('stop').removeAttribute('hidden');
      }
    });
}

function getVideoMetadata(videoUrl, endpoint) {
  return new Promise(resolve => {
    let url = new URL(`/api/video/${endpoint}/`, window.location.href);
    url.searchParams.append('video', encodeURIComponent(videoUrl));
    fetch(url.href)
      .then(response => response.json())
      .then(data => resolve(data['result']))
      .catch(data => resolve(false));
  });
}

async function getVideoDuration(video) {
  return await getVideoMetadata(video, 'durationSeconds');
}

async function getVideoTitle(video) {
  return await getVideoMetadata(video, 'title');
}

async function getVideoThumbnail(video) {
  return await getVideoMetadata(video, 'thumbnail');
}

// ====================================================================
// math / parsing logic
// ====================================================================
const URL_TYPE = {
  VIDEO: 'VIDEO',
  VIDEO_IN_PLAYLIST: 'VIDEO_IN_PLAYLIST',
  PLAYLIST: 'PLAYLIST',
  INVALID: 'INVALID',
};

function getUrlType(url) {
  // for how i got this regex result see
  // https://stackoverflow.com/a/37704433
  // https://regex101.com/r/vHEc61/1
  const youtubeUrlRegex =
  /^((?:https?:)?\/\/)?((?:www|m)\.)?((?:youtube(-nocookie)?\.com|youtu.be))(\/(?:[\w\-]+\?v=|embed\/|v\/)?)([\w\-]+)(\S+)?$/;
  const videoResult = youtubeUrlRegex.exec(url);
  /**
   * our regex for a valid url returns an array like:
   * 0: "https://www.youtube.com/playlist?list=PLj7JwttZwBUTiAqmdB_CUMBaTGapwoH87"
   * 1: "https://"
   * 2: "www."
   * 3: "youtube.com"
   * 4: undefined
   * 5: "/"
   * 6: "playlist"
   * 7: "?list=PLj7JwttZwBUTiAqmdB_CUMBaTGapwoH87"
   * 
   * the element at index 3 is the domain. because share URLs (youtu.be) are
   * always links to singular videos, we can assume a url that passed the
   * regex and has the domain youtu.be is of type VIDEO.
   */
  if (!videoResult?.length) {
    return URL_TYPE.INVALID;
  } else if (videoResult[3] === 'youtu.be') {
    return URL_TYPE.VIDEO;
  }

  // if regex passed it means the url has a question mark in it so
  // .split('?') will return a 2 element array
  const searchParams = new URLSearchParams(url.split('?')[1]);
  const urlHasList = searchParams.has('list');
  const urlHasVideo = searchParams.has('v');

  const lookupTable = {
    true: {
      true: URL_TYPE.VIDEO_IN_PLAYLIST,
      false: URL_TYPE.VIDEO,
    },
    false: {
      true: URL_TYPE.PLAYLIST,
      false: URL_TYPE.INVALID,
    }
  };
  return lookupTable[urlHasVideo][urlHasList];
}

async function handleVideoDuration(event) {
  const { value: clipboardContents } = document.getElementById('url');
  if (!clipboardContents) {
    return;
  }
  const durationSeconds = await getVideoDuration(clipboardContents);
  if (!durationSeconds) {
    return;
  }
  document.getElementById('last-requested-duration-url').value = clipboardContents;
  let secondsInput = document.getElementById("start-offset-seconds");
  secondsInput.min = '0';
  secondsInput.max = '' + durationSeconds;
  // assume we want to start from the beginning
  secondsInput.value = '0';
  secondsInput.removeAttribute('hidden');
  // render the input's value being zero
  humanizeTimeSliderValue({
    target: {
      value: 0,
      max: durationSeconds,
    },
  });
}

function humanizeSecondsDuration(durationInSeconds) {
  let value = durationInSeconds;
  const SECONDS_PER_HOUR = 3600;
  const SECONDS_PER_MINUTE = 60;

  const hoursInSelection = Math.floor(value / SECONDS_PER_HOUR);
  // value is now the remainder of the above division
  value = value % SECONDS_PER_HOUR;

  const minutesInSelection = Math.floor(value / SECONDS_PER_MINUTE);
  // value is now the remainder of the above division
  value = value % SECONDS_PER_MINUTE;

  // https://stackoverflow.com/a/8513046
  const humanizedHours = ('0' + hoursInSelection).slice(-2);
  const humanizedMinutes = ('0' + minutesInSelection).slice(-2);
  const humanizedSeconds = ('0' + value).slice(-2);
  return `${humanizedHours}:${humanizedMinutes}:${humanizedSeconds}`;
}

function humanizeTimeSliderValue(event) {
  const selectedTime = humanizeSecondsDuration(event.target.value);
  const totalTime = humanizeSecondsDuration(Number(event.target.max));
  const humanizedString = `Start time: ${selectedTime} / ${totalTime}`;
  document.getElementById('humanized-start-time').textContent = humanizedString;
}

function getBaseUrl(url) {
  return url.trim().split('&')[0];
}


// ====================================================================
// event handlers
// ====================================================================
function handleUrlChange(event) {
  const overrideMetadataRestrictions = event.keyCode && event.keyCode === 13;
  maybeRenderVideoMetadata(event, overrideMetadataRestrictions);
  hideOrShowDurationSlider(event);
}

(async function () {
  const state = await getServerState();
  if (state && state.now_playing) {
    document.querySelector('.now-playing').style.display = '';
    document.getElementById('stop').removeAttribute('hidden');
    document.getElementById('video-title').removeAttribute('hidden');
    const { title, thumbnail } = state.now_playing;
    renderTitle(title);
    renderThumbnail(thumbnail);
  }
  document.getElementById('url').focus();
}());

document.getElementById('submit').addEventListener('click', handleSubmit);
document.getElementById('stop').addEventListener('click', handleStop);
document.getElementById('url').addEventListener('input', handleUrlChange);
// to override restrictions on one metadata request
document.getElementById('url').addEventListener('keydown', handleUrlChange);
document.getElementById('get-video-seconds').addEventListener('click', handleVideoDuration);
document.getElementById('loop-video').addEventListener('click', toggleVideoLoop);
document.getElementById('start-offset-seconds').addEventListener('input', humanizeTimeSliderValue);
