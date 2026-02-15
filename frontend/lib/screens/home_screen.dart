import 'dart:async';

import 'package:audio_waveforms/audio_waveforms.dart' hide PlayerState;
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:just_audio/just_audio.dart' as ja;

import '../services/api_service.dart';
import 'job_detail_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  static const String _demoUserId = 'demo-user';
  static const List<Map<String, String>> _ttsPresets = [
    {
      'id': 'kokoro_alpha',
      'provider': 'kokoro',
      'voice': 'jf_alpha',
      'label': '[kokoro] alpha',
    },
    {
      'id': 'voicebox_zundamon',
      'provider': 'voicevox',
      'voice': '3',
      'label': '[voicebox] ずんだもん',
    },
    {
      'id': 'voicebox_metan',
      'provider': 'voicevox',
      'voice': '2',
      'label': '[voicebox] 四国めたん',
    },
    {
      'id': 'voicebox_tsumugi',
      'provider': 'voicevox',
      'voice': '8',
      'label': '[voicebox] 春日部つむぎ',
    },
    {
      'id': 'voicebox_whitecul',
      'provider': 'voicevox',
      'voice': '23',
      'label': '[voicebox] WhiteCUL',
    },
  ];

  final ApiService _api = ApiService();
  final TextEditingController _topicController =
      TextEditingController(text: 'AI');

  final ja.AudioPlayer _audioPlayer = ja.AudioPlayer();
  final PlayerController _waveformController = PlayerController();

  StreamSubscription<Duration>? _positionSub;
  StreamSubscription<Duration?>? _durationSub;
  StreamSubscription<ja.PlayerState>? _playerStateSub;

  bool _loadingFeed = false;
  bool _creatingJob = false;
  List<Map<String, dynamic>> _items = [];
  String? _error;
  String? _activeJobId;
  String? _latestJobId;
  String? _latestTopic;
  String? _jobStage;
  String _selectedTtsPresetId = 'kokoro_alpha';
  List<Map<String, dynamic>> _latestAgendaNodes = [];
  List<Map<String, dynamic>> _latestTranscriptSections = [];
  double _jobProgressRatio = 0.0;
  int _jobGeneratedSections = 0;
  int _jobSynthesizedSections = 0;
  int _jobTotalSections = 0;
  Timer? _jobPollTimer;
  ja.ConcatenatingAudioSource? _liveQueue;
  bool _liveQueueAttached = false;
  final Set<String> _queuedChunkFilenames = {};

  String? _currentEpisodeId;
  String? _currentTitle;
  String? _currentAudioUrl;
  Duration _position = Duration.zero;
  Duration _duration = Duration.zero;
  bool _isPlaying = false;

  Map<String, String> get _selectedTtsPreset {
    for (final p in _ttsPresets) {
      if (p['id'] == _selectedTtsPresetId) return p;
    }
    return _ttsPresets.first;
  }

  @override
  void initState() {
    super.initState();
    _bindPlayerStreams();
    _loadFeed();
  }

  void _bindPlayerStreams() {
    _positionSub = _audioPlayer.positionStream.listen((d) {
      if (!mounted) return;
      setState(() => _position = d);
    });
    _durationSub = _audioPlayer.durationStream.listen((d) {
      if (!mounted) return;
      setState(() => _duration = d ?? Duration.zero);
    });
    _playerStateSub = _audioPlayer.playerStateStream.listen((state) {
      if (!mounted) return;
      setState(() => _isPlaying = state.playing);
    });
  }

  @override
  void dispose() {
    _jobPollTimer?.cancel();
    _positionSub?.cancel();
    _durationSub?.cancel();
    _playerStateSub?.cancel();
    _audioPlayer.dispose();
    _waveformController.dispose();
    _topicController.dispose();
    super.dispose();
  }

  Future<void> _loadFeed() async {
    setState(() {
      _loadingFeed = true;
      _error = null;
    });
    try {
      final data = await _api.getFeed(userId: _demoUserId, limit: 20);
      final rawItems = (data['items'] as List?) ?? [];
      setState(() {
        _items = rawItems.map((e) => Map<String, dynamic>.from(e)).toList();
      });
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) {
        setState(() => _loadingFeed = false);
      }
    }
  }

  Future<void> _generateFromTopic() async {
    final topic = _topicController.text.trim();
    if (topic.isEmpty) return;

    setState(() => _creatingJob = true);
    try {
      final created = await _api.createJob(
        topic: topic,
        topK: 2,
        maxArticles: 8,
        ttsProvider: _selectedTtsPreset['provider'],
        ttsVoice: _selectedTtsPreset['voice'],
        ttsSpeed: 1.0,
      );
      final jobId = created['job_id']?.toString();
      if (jobId == null || jobId.isEmpty) {
        throw Exception('Job id not returned');
      }
      _startJobPolling(jobId);
      if (!mounted) return;
      setState(() {
        _latestJobId = jobId;
        _latestTopic = topic;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Job queued: $jobId')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Generation failed: $e')),
      );
    } finally {
      if (mounted) {
        setState(() => _creatingJob = false);
      }
    }
  }

  void _startJobPolling(String jobId) {
    _jobPollTimer?.cancel();
    _liveQueue = ja.ConcatenatingAudioSource(children: []);
    _liveQueueAttached = false;
    _queuedChunkFilenames.clear();
    setState(() {
      _activeJobId = jobId;
      _latestJobId = jobId;
      _jobStage = 'queued';
      _latestAgendaNodes = [];
      _latestTranscriptSections = [];
      _jobProgressRatio = 0.0;
      _jobGeneratedSections = 0;
      _jobSynthesizedSections = 0;
      _jobTotalSections = 0;
    });

    _jobPollTimer = Timer.periodic(const Duration(seconds: 3), (timer) async {
      try {
        final status = await _api.getJobStatus(jobId);
        final state = (status['status'] ?? 'queued').toString();
        final stage = (status['stage'] ?? state).toString();
        final metrics =
            Map<String, dynamic>.from((status['metrics'] as Map?) ?? const {});
        final result =
            Map<String, dynamic>.from((status['result'] as Map?) ?? const {});
        final progress =
            Map<String, dynamic>.from((metrics['progress'] as Map?) ?? const {});
        final agendaRaw = (metrics['agenda_nodes'] as List?) ??
            (result['agenda_nodes'] as List?) ??
            const [];
        final transcriptRaw = (metrics['transcript_sections'] as List?) ??
            (result['transcript_sections'] as List?) ??
            const [];
        if (!mounted) return;
        setState(() {
          _jobStage = stage;
          _latestAgendaNodes =
              agendaRaw.map((e) => Map<String, dynamic>.from(e)).toList();
          _latestTranscriptSections =
              transcriptRaw.map((e) => Map<String, dynamic>.from(e)).toList();
          _jobProgressRatio = (progress['progress_ratio'] is num)
              ? (progress['progress_ratio'] as num).toDouble()
              : _jobProgressRatio;
          _jobGeneratedSections = (progress['generated_sections'] is num)
              ? (progress['generated_sections'] as num).toInt()
              : _jobGeneratedSections;
          _jobSynthesizedSections = (progress['synthesized_sections'] is num)
              ? (progress['synthesized_sections'] as num).toInt()
              : _jobSynthesizedSections;
          _jobTotalSections = (progress['total_sections'] is num)
              ? (progress['total_sections'] as num).toInt()
              : _jobTotalSections;
          _latestTopic =
              (metrics['topic']?.toString().trim().isNotEmpty ?? false)
                  ? metrics['topic'].toString()
                  : _latestTopic;
        });

        final readyChunksRaw =
            (metrics['ready_audio_chunks'] as List?) ?? const [];
        final readyChunkFilenames = readyChunksRaw
            .map((e) => e.toString())
            .where((s) => s.isNotEmpty)
            .toList();
        if (readyChunkFilenames.isNotEmpty) {
          await _enqueueReadyChunks(jobId, readyChunkFilenames);
        }

        if (state == 'completed') {
          timer.cancel();
          await _loadFeed();
          if (!mounted) return;
          setState(() {
            _activeJobId = null;
            _jobStage = null;
            _jobProgressRatio = 1.0;
          });
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Podcast generation completed (auto-switched)'),
            ),
          );
          return;
        }

        if (state == 'failed') {
          timer.cancel();
          if (!mounted) return;
          setState(() {
            _activeJobId = null;
            _jobStage = null;
          });
          final err = status['error']?.toString() ?? 'Job failed';
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(err)),
          );
        }
      } catch (_) {
        if (!mounted) return;
        setState(() {
          _error = 'Job polling failed. Check API connectivity.';
        });
        debugPrint('Job polling failed for $jobId');
      }
    });
  }

  Future<void> _playItem(Map<String, dynamic> item) async {
    final rawAudio = (item['audio_url'] ?? '').toString();
    if (rawAudio.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('No audio URL in this feed item')),
      );
      return;
    }

    final absoluteUrl = ApiService.resolveAudioUrl(rawAudio);
    final episodeId = (item['episode_id'] ?? '').toString();
    final jobId = (item['job_id'] ?? '').toString();
    final title = (item['topic'] ?? 'Untitled').toString();

    try {
      debugPrint('setUrl START');
      _liveQueueAttached = false;
      _liveQueue = null;
      _queuedChunkFilenames.clear();
      await _audioPlayer.setUrl(absoluteUrl);
      debugPrint('setUrl DONE');

      /*await _waveformController.preparePlayer(
        path: absoluteUrl,
        shouldExtractWaveform: true,
        noOfSamples: 120,
      );_*/
      await _audioPlayer.play();

      setState(() {
        _currentEpisodeId = episodeId;
        _currentTitle = title;
        _currentAudioUrl = absoluteUrl;
        if (jobId.isNotEmpty) {
          _latestJobId = jobId;
        }
      });

      if (episodeId.isNotEmpty) {
        unawaited(
          _api.trackEvent(
            userId: _demoUserId,
            episodeId: episodeId,
            eventType: 'play_start',
          ),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Playback failed: $e')),
      );
    }
  }

  Future<void> _togglePlayPause() async {
    if (_currentAudioUrl == null) return;
    if (_isPlaying) {
      await _audioPlayer.pause();
    } else {
      await _audioPlayer.play();
    }
  }

  Future<void> _seekTo(Duration d) async {
    await _audioPlayer.seek(d);
    try {
      await _waveformController.seekTo(d.inMilliseconds);
    } catch (_) {}
  }

  String _format(Duration d) {
    final mm = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final ss = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$mm:$ss';
  }

  Future<void> _enqueueReadyChunks(
    String jobId,
    List<String> chunkFilenames,
  ) async {
    if (_activeJobId != jobId) return;
    final queue = _liveQueue;
    if (queue == null) return;

    var hasNewChunk = false;
    for (final filename in chunkFilenames) {
      if (_queuedChunkFilenames.contains(filename)) continue;
      final url = ApiService.resolveAudioUrl('/audio/$filename');
      await queue.add(
        ja.AudioSource.uri(Uri.parse(url)),
      );
      _queuedChunkFilenames.add(filename);
      hasNewChunk = true;
    }

    if (!hasNewChunk) return;

    if (!_liveQueueAttached) {
      await _audioPlayer.setAudioSource(queue);
      _liveQueueAttached = true;
      await _audioPlayer.play();
      if (!mounted) return;
      setState(() {
        _currentEpisodeId = '';
        _currentTitle = 'Generating... (Live Chapters)';
        _currentAudioUrl = 'live_queue';
      });
      return;
    }

    if (!_audioPlayer.playing) {
      await _audioPlayer.play();
    }
  }

  void _openJobDetail() {
    final jobId = _activeJobId ?? _latestJobId;
    if (jobId == null || jobId.isEmpty) return;
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => JobDetailScreen(
          jobId: jobId,
          player: _audioPlayer,
          initialTopic: _latestTopic ?? _topicController.text.trim(),
          initialStage: _jobStage,
          initialAgendaNodes: _latestAgendaNodes,
          initialTranscriptSections: _latestTranscriptSections,
          initialProgressRatio: _jobProgressRatio,
          initialGeneratedSections: _jobGeneratedSections,
          initialSynthesizedSections: _jobSynthesizedSections,
          initialTotalSections: _jobTotalSections,
        ),
      ),
    );
  }

  void _onTapPlayerTitle() {
    final jobId = _activeJobId ?? _latestJobId;
    if (jobId == null || jobId.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('詳細を開くためのジョブ情報がありません')),
      );
      return;
    }
    _openJobDetail();
  }

  Widget _buildPlayerPanel() {
    if (_currentAudioUrl == null) return const SizedBox.shrink();
    final canOpenDetail = (_activeJobId ?? _latestJobId)?.isNotEmpty == true;

    final maxMs = _duration.inMilliseconds <= 0 ? 1 : _duration.inMilliseconds;
    final posMs = _position.inMilliseconds.clamp(0, maxMs).toDouble();

    return Container(
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceVariant.withOpacity(0.8),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: InkWell(
                  onTap: _onTapPlayerTitle,
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Text(
                      _currentTitle ?? 'Now Playing',
                      style: GoogleFonts.inter(
                        fontWeight: FontWeight.w700,
                        decoration: TextDecoration.underline,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ),
              ),
              if (canOpenDetail)
                IconButton(
                  onPressed: _openJobDetail,
                  icon: const Icon(Icons.open_in_new, size: 18),
                  tooltip: 'Open job detail',
                ),
            ],
          ),
          const SizedBox(height: 8),
          AudioFileWaveforms(
            size: const Size(double.infinity, 70),
            playerController: _waveformController,
            waveformType: WaveformType.fitWidth,
            enableSeekGesture: true,
            playerWaveStyle: const PlayerWaveStyle(
              fixedWaveColor: Color(0x553B82F6),
              liveWaveColor: Color(0xFF3B82F6),
              spacing: 4,
              waveThickness: 2,
            ),
          ),
          Slider(
            value: posMs,
            max: maxMs.toDouble(),
            onChanged: (v) => _seekTo(Duration(milliseconds: v.toInt())),
          ),
          Row(
            children: [
              IconButton(
                onPressed: _togglePlayPause,
                icon: Icon(_isPlaying ? Icons.pause : Icons.play_arrow),
              ),
              Text('${_format(_position)} / ${_format(_duration)}'),
            ],
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('StepWise',
            style: GoogleFonts.outfit(fontWeight: FontWeight.w700)),
        actions: [
          IconButton(
            onPressed: _loadingFeed ? null : _loadFeed,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                    controller: _topicController,
                    decoration: const InputDecoration(
                      labelText: 'Generate topic',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                ElevatedButton(
                  onPressed: _creatingJob ? null : _generateFromTopic,
                  child: Text(_creatingJob ? 'Generating...' : 'Create'),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: DropdownButtonFormField<String>(
              value: _selectedTtsPresetId,
              decoration: const InputDecoration(
                labelText: 'TTS Voice',
                border: OutlineInputBorder(),
              ),
              items: _ttsPresets
                  .map(
                    (p) => DropdownMenuItem<String>(
                      value: p['id'],
                      child: Text(p['label'] ?? ''),
                    ),
                  )
                  .toList(),
              onChanged: _creatingJob
                  ? null
                  : (v) {
                      if (v == null) return;
                      setState(() => _selectedTtsPresetId = v);
                    },
            ),
          ),
          if (_latestJobId != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: Material(
                color: Theme.of(context).colorScheme.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(12),
                child: InkWell(
                  borderRadius: BorderRadius.circular(12),
                  onTap: _openJobDetail,
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const SizedBox(
                              width: 14,
                              height: 14,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                'Job $_latestJobId: ${_jobStage ?? 'completed'}',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            const Icon(Icons.open_in_new, size: 18),
                          ],
                        ),
                        const SizedBox(height: 8),
                        LinearProgressIndicator(
                          value: _jobProgressRatio.clamp(0.0, 1.0),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          'progress: $_jobSynthesizedSections / ${_jobTotalSections == 0 ? '-' : _jobTotalSections} (generated: $_jobGeneratedSections)',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.all(12),
              child: Text(
                _error!,
                style: const TextStyle(color: Colors.redAccent),
              ),
            ),
          Expanded(
            child: _loadingFeed
                ? const Center(child: CircularProgressIndicator())
                : _items.isEmpty
                    ? const Center(child: Text('No feed items yet'))
                    : RefreshIndicator(
                        onRefresh: _loadFeed,
                        child: ListView.separated(
                          padding: const EdgeInsets.all(16),
                          itemCount: _items.length,
                          separatorBuilder: (_, __) =>
                              const SizedBox(height: 10),
                          itemBuilder: (context, index) {
                            final item = _items[index];
                            return Card(
                              child: ListTile(
                                onTap: () => _playItem(item),
                                title: Text(
                                    item['topic']?.toString() ?? 'Untitled'),
                                subtitle: Text(
                                  'reason: ${item['reason'] ?? '-'} | score: ${item['score'] ?? 0}',
                                ),
                                trailing: const Icon(Icons.play_circle_fill),
                              ),
                            );
                          },
                        ),
                      ),
          ),
          _buildPlayerPanel(),
        ],
      ),
    );
  }
}
