import 'dart:async';

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:just_audio/just_audio.dart' as ja;

import '../services/api_service.dart';

class JobDetailScreen extends StatefulWidget {
  const JobDetailScreen({
    super.key,
    required this.jobId,
    required this.player,
    this.initialTopic,
    this.initialStage,
    this.initialAgendaNodes = const [],
    this.initialTranscriptSections = const [],
    this.initialProgressRatio = 0.0,
    this.initialGeneratedSections = 0,
    this.initialSynthesizedSections = 0,
    this.initialTotalSections = 0,
  });

  final String jobId;
  final ja.AudioPlayer player;
  final String? initialTopic;
  final String? initialStage;
  final List<Map<String, dynamic>> initialAgendaNodes;
  final List<Map<String, dynamic>> initialTranscriptSections;
  final double initialProgressRatio;
  final int initialGeneratedSections;
  final int initialSynthesizedSections;
  final int initialTotalSections;

  @override
  State<JobDetailScreen> createState() => _JobDetailScreenState();
}

class _JobDetailScreenState extends State<JobDetailScreen> {
  final ApiService _api = ApiService();
  Timer? _pollTimer;

  String? _topic;
  String? _stage;
  String? _error;
  List<Map<String, dynamic>> _agendaNodes = [];
  List<Map<String, dynamic>> _transcriptSections = [];
  double _progressRatio = 0.0;
  int _generatedSections = 0;
  int _synthesizedSections = 0;
  int _totalSections = 0;
  String _ttsProviderRequested = 'kokoro';
  String _ttsVoiceRequested = 'jf_alpha';
  String _ttsProviderUsed = 'kokoro';
  String _ttsVoiceUsed = 'jf_alpha';
  double _playbackSpeed = 1.0;

  static const List<double> _speedOptions = [
    0.5,
    1.0,
    1.25,
    1.5,
    1.75,
    2.0,
    2.5,
    3.0,
  ];

  Duration _position = Duration.zero;
  Duration _duration = Duration.zero;
  bool _isPlaying = false;
  int? _currentSourceIndex;
  List<String> _readyAudioChunks = [];
  StreamSubscription<Duration>? _positionSub;
  StreamSubscription<Duration?>? _durationSub;
  StreamSubscription<ja.PlayerState>? _playerStateSub;
  StreamSubscription<int?>? _currentIndexSub;

  @override
  void initState() {
    super.initState();
    _topic = widget.initialTopic;
    _stage = widget.initialStage;
    _agendaNodes = List<Map<String, dynamic>>.from(widget.initialAgendaNodes);
    _transcriptSections =
        List<Map<String, dynamic>>.from(widget.initialTranscriptSections);
    _progressRatio = widget.initialProgressRatio;
    _generatedSections = widget.initialGeneratedSections;
    _synthesizedSections = widget.initialSynthesizedSections;
    _totalSections = widget.initialTotalSections;
    _bindPlayerStreams();
    _startPolling();
  }

  void _bindPlayerStreams() {
    _positionSub = widget.player.positionStream.listen((d) {
      if (!mounted) return;
      setState(() => _position = d);
    });
    _durationSub = widget.player.durationStream.listen((d) {
      if (!mounted) return;
      setState(() => _duration = d ?? Duration.zero);
    });
    _playerStateSub = widget.player.playerStateStream.listen((state) {
      if (!mounted) return;
      setState(() => _isPlaying = state.playing);
    });
    _currentIndexSub = widget.player.currentIndexStream.listen((idx) {
      if (!mounted) return;
      setState(() => _currentSourceIndex = idx);
    });
    _playbackSpeed = widget.player.speed;
  }

  void _startPolling() {
    _pollTimer?.cancel();
    unawaited(_pollOnce());
    _pollTimer = Timer.periodic(const Duration(seconds: 3), (_) async {
      await _pollOnce();
    });
  }

  Future<void> _pollOnce() async {
    try {
      final status = await _api.getJobStatus(widget.jobId);
      final metrics =
          Map<String, dynamic>.from((status['metrics'] as Map?) ?? const {});
      final result =
          Map<String, dynamic>.from((status['result'] as Map?) ?? const {});

      final progress =
          Map<String, dynamic>.from((metrics['progress'] as Map?) ?? const {});
      final readyChunksRaw = (metrics['ready_audio_chunks'] as List?) ??
          (result['ready_audio_chunks'] as List?) ??
          const [];

      final agendaRaw = (metrics['agenda_nodes'] as List?) ??
          (result['agenda_nodes'] as List?) ??
          const [];
      final transcriptRaw = (metrics['transcript_sections'] as List?) ??
          (result['transcript_sections'] as List?) ??
          const [];

      if (!mounted) return;
      setState(() {
        _stage = (status['stage'] ?? status['status'] ?? '').toString();
        _topic = (metrics['topic'] ?? result['topic'] ?? _topic ?? '').toString();
        _ttsProviderRequested = (metrics['tts_provider_requested'] ??
                result['tts_provider_requested'] ??
                _ttsProviderRequested)
            .toString();
        _ttsVoiceRequested = (metrics['tts_voice_requested'] ??
                result['tts_voice_requested'] ??
                _ttsVoiceRequested)
            .toString();
        _ttsProviderUsed = (metrics['tts_provider_used'] ??
                result['tts_provider_used'] ??
                _ttsProviderUsed)
            .toString();
        _ttsVoiceUsed = (metrics['tts_voice_used'] ??
                result['tts_voice_used'] ??
                _ttsVoiceUsed)
            .toString();

        _agendaNodes = agendaRaw.map((e) => Map<String, dynamic>.from(e)).toList();
        _transcriptSections =
            transcriptRaw.map((e) => Map<String, dynamic>.from(e)).toList();
        _readyAudioChunks = readyChunksRaw.map((e) => e.toString()).toList();
        _progressRatio = (progress['progress_ratio'] is num)
            ? (progress['progress_ratio'] as num).toDouble()
            : _progressRatio;
        _generatedSections = (progress['generated_sections'] is num)
            ? (progress['generated_sections'] as num).toInt()
            : _generatedSections;
        _synthesizedSections = (progress['synthesized_sections'] is num)
            ? (progress['synthesized_sections'] as num).toInt()
            : _synthesizedSections;
        _totalSections = (progress['total_sections'] is num)
            ? (progress['total_sections'] as num).toInt()
            : _totalSections;
        _error = status['error']?.toString();
      });

      final state = (status['status'] ?? '').toString();
      if (state == 'completed' || state == 'failed') {
        _pollTimer?.cancel();
      }
    } catch (_) {
      // keep last known data and retry next tick
    }
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _positionSub?.cancel();
    _durationSub?.cancel();
    _playerStateSub?.cancel();
    _currentIndexSub?.cancel();
    super.dispose();
  }

  Future<void> _togglePlayPause() async {
    if (_isPlaying) {
      await widget.player.pause();
    } else {
      await widget.player.play();
    }
  }

  Future<void> _seekTo(Duration d) async {
    await widget.player.seek(d);
  }

  String _format(Duration d) {
    final mm = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final ss = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$mm:$ss';
  }

  String _formatSpeed(double s) {
    if (s == s.roundToDouble()) return '${s.toInt()}x';
    return '${s}x';
  }

  String _voiceDisplayName(String provider, String voice) {
    final p = provider.toLowerCase();
    if (p == 'kokoro') {
      if (voice == 'jf_alpha') return '[kokoro] alpha';
      return '[kokoro] $voice';
    }
    if (p == 'voicevox') {
      if (voice == '3') return '[voicebox] ずんだもん';
      if (voice == '2') return '[voicebox] 四国めたん';
      if (voice == '8') return '[voicebox] 春日部つむぎ';
      if (voice == '23') return '[voicebox] WhiteCUL';
      return '[voicebox] speaker $voice';
    }
    return '[$provider] $voice';
  }

  String _speakerLabel(String speaker) {
    if (speaker == 'A') {
      final provider = _ttsProviderRequested.isNotEmpty
          ? _ttsProviderRequested
          : _ttsProviderUsed;
      final voice = _ttsVoiceRequested.isNotEmpty
          ? _ttsVoiceRequested
          : _ttsVoiceUsed;
      return 'A (${_voiceDisplayName(provider, voice)})';
    }
    return speaker;
  }
  int _lineWeight(String text) {
    final cleaned = text.trim();
    if (cleaned.isEmpty) return 1;
    return cleaned.length.clamp(1, 400);
  }

  List<Map<String, dynamic>> _flattenTranscriptLines() {
    final out = <Map<String, dynamic>>[];
    for (final section in _transcriptSections) {
      final lines = (section['lines'] as List?) ?? const [];
      for (final line in lines) {
        final row = Map<String, dynamic>.from((line as Map?) ?? const {});
        out.add(row);
      }
    }
    return out;
  }

  List<int> _allLineWeights() {
    final out = <int>[];
    for (final section in _transcriptSections) {
      final lines = (section['lines'] as List?) ?? const [];
      for (final line in lines) {
        final row = Map<String, dynamic>.from((line as Map?) ?? const {});
        out.add(_lineWeight((row['text'] ?? '').toString()));
      }
    }
    return out;
  }

  Map<String, int> _activeSectionLine() {
    if (_transcriptSections.isEmpty) {
      return const {'section': -1, 'line': -1};
    }
    final posMs = _position.inMilliseconds;

    // Prefer source-index based highlighting when playing concatenated sections.
    final currentSourceIdx = _currentSourceIndex;
    if (currentSourceIdx != null) {
      final sectionToSource = _buildSectionToSourceIndexMap();
      int? sectionNumber;
      for (final entry in sectionToSource.entries) {
        if (entry.value == currentSourceIdx) {
          sectionNumber = entry.key;
          break;
        }
      }
      if (sectionNumber != null) {
        final sectionListIdx = _findSectionListIndexBySectionNumber(sectionNumber);
        if (sectionListIdx >= 0) {
          final sec = Map<String, dynamic>.from(_transcriptSections[sectionListIdx]);
          final lineIdx = _activeLineInSection(sec, posMs);
          return {'section': sectionListIdx, 'line': lineIdx};
        }
      }
    }

    var activeSection = -1;
    for (var i = 0; i < _transcriptSections.length; i++) {
      final sec = Map<String, dynamic>.from(_transcriptSections[i]);
      final start = (sec['global_start_ms'] as num?)?.toInt() ??
          _estimatedSectionStartMs(i);
      var end = (sec['global_end_ms'] as num?)?.toInt() ?? -1;
      if (end <= start) {
        final d = _sectionDurationMs(sec);
        end = d > 0 ? start + d : start;
      }
      if (posMs >= start && posMs < end) {
        activeSection = i;
        break;
      }
    }
    if (activeSection < 0) {
      if (_position.inMilliseconds <= 0) {
        activeSection = 0;
      } else {
        activeSection = _transcriptSections.length - 1;
      }
    }

    final section = Map<String, dynamic>.from(_transcriptSections[activeSection]);
    final lines = ((section['lines'] as List?) ?? const [])
        .map((e) => Map<String, dynamic>.from((e as Map?) ?? const {}))
        .toList();
    if (lines.isEmpty) {
      return {'section': activeSection, 'line': -1};
    }

    for (var i = 0; i < lines.length; i++) {
      final line = lines[i];
      final s = (line['global_start_ms'] as num?)?.toInt() ?? -1;
      final e = (line['global_end_ms'] as num?)?.toInt() ?? -1;
      if (s >= 0 && e > s && posMs >= s && posMs < e) {
        return {'section': activeSection, 'line': i};
      }
    }

    final sectionStart = (section['global_start_ms'] as num?)?.toInt() ??
        _estimatedSectionStartMs(activeSection);
    final relMs = (posMs - sectionStart).clamp(0, 1 << 30);
    for (var i = 0; i < lines.length; i++) {
      final line = lines[i];
      final s = (line['start_ms'] as num?)?.toInt() ?? -1;
      final e = (line['end_ms'] as num?)?.toInt() ?? -1;
      if (s >= 0 && e > s && relMs >= s && relMs < e) {
        return {'section': activeSection, 'line': i};
      }
    }

    final weights = lines
        .map((row) => _lineWeight((row['text'] ?? '').toString()))
        .toList();
    final totalWeight = weights.fold<int>(0, (sum, w) => sum + w).clamp(1, 10000000);
    final sectionDurationMs = _sectionDurationMs(section);
    final ratio = sectionDurationMs > 0
        ? (relMs / sectionDurationMs).clamp(0.0, 1.0)
        : 0.0;
    final target = (totalWeight * ratio).round();
    var acc = 0;
    for (var i = 0; i < weights.length; i++) {
      acc += weights[i];
      if (target <= acc) {
        return {'section': activeSection, 'line': i};
      }
    }
    return {'section': activeSection, 'line': lines.length - 1};
  }

  Future<void> _seekToGlobalLine(int targetIndex) async {
    final flatLines = _flattenTranscriptLines();
    if (targetIndex < 0 || targetIndex >= flatLines.length) return;

    final targetLine = flatLines[targetIndex];
    final strictStart = (targetLine['global_start_ms'] as num?)?.toInt();
    final strictEnd = (targetLine['global_end_ms'] as num?)?.toInt();
    if (strictStart != null &&
        strictEnd != null &&
        strictStart >= 0 &&
        strictEnd > strictStart) {
      await _seekTo(Duration(milliseconds: strictStart));
      return;
    }

    // Fallback 1: section-local proportional seek using section timing metadata.
    var globalCursor = 0;
    for (final section in _transcriptSections) {
      final lines = (section['lines'] as List?) ?? const [];
      final sectionLineCount = lines.length;
      if (targetIndex >= globalCursor && targetIndex < globalCursor + sectionLineCount) {
        final localIndex = targetIndex - globalCursor;
        final sectionStart = (section['global_start_ms'] as num?)?.toInt() ?? -1;
        final sectionEnd = (section['global_end_ms'] as num?)?.toInt() ?? -1;
        var sectionAudioMs = (section['audio_ms'] as num?)?.toInt() ?? 0;
        if (sectionAudioMs <= 0 && sectionStart >= 0 && sectionEnd > sectionStart) {
          sectionAudioMs = sectionEnd - sectionStart;
        }
        if (sectionStart >= 0 && sectionAudioMs > 0) {
          final sectionRows = lines
              .map((e) => Map<String, dynamic>.from((e as Map?) ?? const {}))
              .toList();
          final weights = sectionRows
              .map((row) => _lineWeight((row['text'] ?? '').toString()))
              .toList();
          final totalWeight =
              weights.fold<int>(0, (sum, w) => sum + w).clamp(1, 10000000);
          var prefix = 0;
          for (var i = 0; i < localIndex && i < weights.length; i++) {
            prefix += weights[i];
          }
          final sectionOffset = ((sectionAudioMs * (prefix / totalWeight))).round();
          await _seekTo(Duration(milliseconds: sectionStart + sectionOffset));
          return;
        }
        break;
      }
      globalCursor += sectionLineCount;
    }

    if (_duration.inMilliseconds <= 0) return;

    final weights = _allLineWeights();
    if (weights.isEmpty || targetIndex >= weights.length) return;
    var totalWeight = 0;
    for (final w in weights) {
      totalWeight += w;
    }
    if (totalWeight <= 0) return;

    var prefix = 0;
    for (var i = 0; i < targetIndex; i++) {
      prefix += weights[i];
    }
    final ratio = (prefix / totalWeight).clamp(0.0, 1.0);
    final ms = (_duration.inMilliseconds * ratio).round();
    await _seekTo(Duration(milliseconds: ms));
  }

  int _sectionDurationMs(Map<String, dynamic> section) {
    final audioMs = (section['audio_ms'] as num?)?.toInt() ?? 0;
    if (audioMs > 0) return audioMs;
    final gs = (section['global_start_ms'] as num?)?.toInt() ?? -1;
    final ge = (section['global_end_ms'] as num?)?.toInt() ?? -1;
    if (gs >= 0 && ge > gs) return ge - gs;
    return 0;
  }

  int _estimatedSectionStartMs(int sectionIndex) {
    if (sectionIndex <= 0) return 0;
    var acc = 0;
    for (var i = 0; i < sectionIndex && i < _transcriptSections.length; i++) {
      final sec = Map<String, dynamic>.from(_transcriptSections[i]);
      var d = _sectionDurationMs(sec);
      if (d <= 0) {
        final lines = (sec['lines'] as List?) ?? const [];
        final approxChars = lines
            .map((e) => Map<String, dynamic>.from((e as Map?) ?? const {}))
            .map((row) => ((row['text'] ?? '').toString().length))
            .fold<int>(0, (sum, v) => sum + v);
        d = (approxChars * 180).clamp(1000, 120000); // rough fallback
      }
      acc += d;
    }
    return acc;
  }

  int _estimatedLineOffsetInSectionMs(
    List<Map<String, dynamic>> lines,
    int lineIndex,
    int sectionDurationMs,
  ) {
    if (lineIndex <= 0) return 0;
    final weights = lines
        .map((row) => _lineWeight((row['text'] ?? '').toString()))
        .toList();
    final totalWeight =
        weights.fold<int>(0, (sum, w) => sum + w).clamp(1, 10000000);
    var prefix = 0;
    for (var i = 0; i < lineIndex && i < weights.length; i++) {
      prefix += weights[i];
    }
    if (sectionDurationMs <= 0) return 0;
    return ((sectionDurationMs * (prefix / totalWeight))).round();
  }

  Map<int, int> _buildSectionToSourceIndexMap() {
    // ready_audio_chunks is already ordered by section_index on backend.
    final sortedReadySections = _transcriptSections
        .map((e) => Map<String, dynamic>.from(e))
        .where((sec) => (sec['status']?.toString() ?? '') == 'ready')
        .toList()
      ..sort((a, b) =>
          ((a['section_index'] as num?)?.toInt() ?? 0)
              .compareTo((b['section_index'] as num?)?.toInt() ?? 0));

    final map = <int, int>{};
    final max = _readyAudioChunks.length < sortedReadySections.length
        ? _readyAudioChunks.length
        : sortedReadySections.length;
    for (var i = 0; i < max; i++) {
      final secIndex =
          ((sortedReadySections[i]['section_index'] as num?)?.toInt() ?? -1);
      if (secIndex >= 0) {
        map[secIndex] = i;
      }
    }
    return map;
  }

  int _findSectionListIndexBySectionNumber(int sectionNumber) {
    for (var i = 0; i < _transcriptSections.length; i++) {
      final sec = Map<String, dynamic>.from(_transcriptSections[i]);
      final n = (sec['section_index'] as num?)?.toInt() ?? -1;
      if (n == sectionNumber) return i;
    }
    return -1;
  }

  int _activeLineInSection(Map<String, dynamic> section, int localPosMs) {
    final lines = ((section['lines'] as List?) ?? const [])
        .map((e) => Map<String, dynamic>.from((e as Map?) ?? const {}))
        .toList();
    if (lines.isEmpty) return -1;

    for (var i = 0; i < lines.length; i++) {
      final line = lines[i];
      final s = (line['start_ms'] as num?)?.toInt() ?? -1;
      final e = (line['end_ms'] as num?)?.toInt() ?? -1;
      if (s >= 0 && e > s && localPosMs >= s && localPosMs < e) {
        return i;
      }
    }

    var sectionDurationMs = _sectionDurationMs(section);
    if (sectionDurationMs <= 0 && _duration.inMilliseconds > 0) {
      sectionDurationMs = _duration.inMilliseconds;
    }
    final weights = lines
        .map((row) => _lineWeight((row['text'] ?? '').toString()))
        .toList();
    final totalWeight =
        weights.fold<int>(0, (sum, w) => sum + w).clamp(1, 10000000);
    final ratio = sectionDurationMs > 0
        ? (localPosMs / sectionDurationMs).clamp(0.0, 1.0)
        : 0.0;
    final target = (totalWeight * ratio).round();
    var acc = 0;
    for (var i = 0; i < weights.length; i++) {
      acc += weights[i];
      if (target <= acc) return i;
    }
    return lines.length - 1;
  }

  Future<void> _seekToSectionLine(
    int sectionIndex,
    int lineIndex, {
    int? globalIndex,
  }) async {
    if (sectionIndex < 0 || sectionIndex >= _transcriptSections.length) return;
    final section = Map<String, dynamic>.from(_transcriptSections[sectionIndex]);
    final linesRaw = (section['lines'] as List?) ?? const [];
    final lines = linesRaw
        .map((e) => Map<String, dynamic>.from((e as Map?) ?? const {}))
        .toList();
    if (lineIndex < 0 || lineIndex >= lines.length) return;
    final targetLine = lines[lineIndex];

    final sectionNumber = (section['section_index'] as num?)?.toInt() ?? sectionIndex;
    var sectionDurationMs = _sectionDurationMs(section);
    if (sectionDurationMs <= 0 && _duration.inMilliseconds > 0) {
      sectionDurationMs =
          (_duration.inMilliseconds / (_transcriptSections.length.clamp(1, 1000)))
              .round();
    }
    final sectionLineStartMs = (targetLine['start_ms'] as num?)?.toInt() ??
        _estimatedLineOffsetInSectionMs(lines, lineIndex, sectionDurationMs);

    final sectionToSource = _buildSectionToSourceIndexMap();
    final mappedSourceIndex = sectionToSource[sectionNumber];
    if (mappedSourceIndex != null && _readyAudioChunks.isNotEmpty) {
      final safeOffset = sectionLineStartMs < 0 ? 0 : sectionLineStartMs;
      try {
        await widget.player.seek(
          Duration(milliseconds: safeOffset),
          index: mappedSourceIndex,
        );
        return;
      } catch (_) {
        // fall through to global seek path
      }
    }

    final strictGlobalStart = (targetLine['global_start_ms'] as num?)?.toInt();
    final strictGlobalEnd = (targetLine['global_end_ms'] as num?)?.toInt();
    if (strictGlobalStart != null &&
        strictGlobalEnd != null &&
        strictGlobalStart >= 0 &&
        strictGlobalEnd > strictGlobalStart) {
      await _seekTo(Duration(milliseconds: strictGlobalStart));
      return;
    }

    final sectionStart = (section['global_start_ms'] as num?)?.toInt() ??
        _estimatedSectionStartMs(sectionIndex);

    final lineStart = (targetLine['start_ms'] as num?)?.toInt();
    final lineEnd = (targetLine['end_ms'] as num?)?.toInt();
    if (lineStart != null &&
        lineEnd != null &&
        lineStart >= 0 &&
        lineEnd > lineStart) {
      await _seekTo(Duration(milliseconds: sectionStart + lineStart));
      return;
    }

    // Fallback in section: weighted offset by line order.
    final weights = lines
        .map((row) => _lineWeight((row['text'] ?? '').toString()))
        .toList();
    final totalWeight = weights.fold<int>(0, (sum, w) => sum + w).clamp(1, 10000000);
    var prefix = 0;
    for (var i = 0; i < lineIndex && i < weights.length; i++) {
      prefix += weights[i];
    }
    if (sectionDurationMs > 0 || sectionStart > 0) {
      final secOffset = sectionDurationMs > 0
          ? ((sectionDurationMs * (prefix / totalWeight))).round()
          : 0;
      await _seekTo(Duration(milliseconds: sectionStart + secOffset));
      return;
    }

    // Last fallback: existing global-line based logic.
    if (globalIndex != null) {
      await _seekToGlobalLine(globalIndex);
    }
  }

  @override
  Widget build(BuildContext context) {
    final maxMs = _duration.inMilliseconds <= 0 ? 1 : _duration.inMilliseconds;
    final posMs = _position.inMilliseconds.clamp(0, maxMs).toDouble();

    return Scaffold(
      appBar: AppBar(
        title: Text('StepWise Job Detail', style: GoogleFonts.outfit()),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                _topic?.isNotEmpty == true ? _topic! : 'Generating...',
                style: GoogleFonts.inter(
                  fontSize: 20,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 8),
              Text('stage: ${_stage ?? 'unknown'}'),
              if (_error != null && _error!.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(
                  _error!,
                  style: const TextStyle(color: Colors.redAccent),
                ),
              ],
              const SizedBox(height: 12),
              Expanded(
                child: SingleChildScrollView(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Agenda',
                          style:
                              GoogleFonts.inter(fontWeight: FontWeight.w700)),
                      const SizedBox(height: 8),
                      if (_agendaNodes.isEmpty)
                        const Text('No agenda yet')
                      else
                        ..._agendaNodes.map((node) => Padding(
                              padding: const EdgeInsets.only(bottom: 6),
                              child: Text(
                                '- ${node['title'] ?? ''} (${node['role'] ?? 'point'})',
                              ),
                            )),
                      const SizedBox(height: 16),
                      Text('Transcript',
                          style:
                              GoogleFonts.inter(fontWeight: FontWeight.w700)),
                      const SizedBox(height: 8),
                      if (_transcriptSections.isEmpty)
                        const Text('No transcript yet')
                      else
                        ...(() {
                          final active = _activeSectionLine();
                          final activeSectionIdx = active['section'] ?? -1;
                          final activeLineIdx = active['line'] ?? -1;
                          var globalIdx = -1;
                          return _transcriptSections.asMap().entries.map((entry) {
                          final sectionIdx = entry.key;
                          final section = entry.value;
                          final title = (section['section_title'] ?? 'Section')
                              .toString();
                          final status = (section['status'] ?? '').toString();
                          final lines = (section['lines'] as List?) ?? const [];
                          return Padding(
                            padding: const EdgeInsets.only(bottom: 12),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('$title [$status]',
                                    style: GoogleFonts.inter(
                                        fontWeight: FontWeight.w600)),
                                const SizedBox(height: 4),
                                ...lines.asMap().entries.map((lineEntry) {
                                  final lineIdx = lineEntry.key;
                                  final line = lineEntry.value;
                                  globalIdx += 1;
                                  final isActive = sectionIdx == activeSectionIdx && lineIdx == activeLineIdx;
                                  final row = Map<String, dynamic>.from(
                                      (line as Map?) ?? const {});
                                  final speaker = (row['speaker'] ?? '-').toString();
                                  final text = '${_speakerLabel(speaker)}: ${row['text'] ?? ''}';
                                  final targetIdx = globalIdx;
                                  return InkWell(
                                    onTap: () => _seekToSectionLine(
                                      sectionIdx,
                                      lineIdx,
                                      globalIndex: targetIdx,
                                    ),
                                    child: Padding(
                                      padding:
                                          const EdgeInsets.symmetric(vertical: 1),
                                      child: Text(
                                        text,
                                        style: TextStyle(
                                          color: isActive
                                              ? Theme.of(context)
                                                  .colorScheme
                                                  .onSurface
                                              : Colors.grey,
                                          fontWeight: isActive
                                              ? FontWeight.w700
                                              : FontWeight.w400,
                                        ),
                                      ),
                                    ),
                                  );
                                }),
                              ],
                            ),
                          );
                        }).toList();
                        })(),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  ElevatedButton.icon(
                    onPressed: _togglePlayPause,
                    icon: Icon(_isPlaying ? Icons.pause : Icons.play_arrow),
                    label: Text(_isPlaying ? 'Pause' : 'Play'),
                  ),
                  const SizedBox(width: 12),
                  DropdownButton<double>(
                    value: _playbackSpeed,
                    items: _speedOptions
                        .map(
                          (s) => DropdownMenuItem<double>(
                            value: s,
                            child: Text(_formatSpeed(s)),
                          ),
                        )
                        .toList(),
                    onChanged: (v) async {
                      if (v == null) return;
                      await widget.player.setSpeed(v);
                      if (!mounted) return;
                      setState(() => _playbackSpeed = v);
                    },
                  ),
                  const SizedBox(width: 12),
                  Text('${_format(_position)} / ${_format(_duration)}'),
                ],
              ),
              Slider(
                value: posMs,
                max: maxMs.toDouble(),
                onChanged: (v) => _seekTo(Duration(milliseconds: v.toInt())),
              ),
              LinearProgressIndicator(value: _progressRatio.clamp(0.0, 1.0)),
              const SizedBox(height: 6),
              Text(
                'progress: $_synthesizedSections / $_totalSections (generated: $_generatedSections)',
              ),
            ],
          ),
        ),
      ),
    );
  }
}
